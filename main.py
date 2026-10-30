import os
from fastapi import FastAPI, Depends, HTTPException, status, UploadFile, File, Form
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from jose import JWTError, jwt
from sqlalchemy.orm import Session
from sqlalchemy import select
from pathlib import Path
from fastapi.staticfiles import StaticFiles
from .database import Base, engine, get_db
from .models import User, JournalEntry
from .schemas import RegisterIn, LoginIn, TokenOut, UserOut, JournalIn, JournalOut
from .security import hash_password, verify_password, create_access_token, SECRET, ALGORITHM
from .schemas import AnalysisIn
from .analysis_engine import analyze_ohlc
from .chart_vision import MAX_IMAGE_BYTES, ALLOWED_TYPES, valid_image, analyze_chart_image

Base.metadata.create_all(bind=engine)
app = FastAPI(title="SKG TRADE I API", version="0.7.0", description="Public registration; analysis-only trading workspace. No order execution.")
origins = [x.strip() for x in os.getenv("CORS_ORIGINS", "http://localhost:5500,http://127.0.0.1:5500,http://localhost:3000").split(",") if x.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["GET", "POST", "DELETE"], allow_headers=["Authorization", "Content-Type"])

@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if os.getenv("APP_ENV", "development").lower() == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response
bearer = HTTPBearer(auto_error=False)

@app.get("/health")
def health():
    return {"status": "ok", "app": "SKG TRADE I", "mode": "analysis_only", "order_execution": False}

@app.post("/api/auth/register", response_model=TokenOut, status_code=201)
def register(payload: RegisterIn, db: Session = Depends(get_db)):
    if os.getenv("PUBLIC_REGISTRATION", "true").lower() != "true":
        raise HTTPException(403, "Public registration is disabled")
    email = payload.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "An account with this email already exists")
    user = User(email=email, full_name=payload.full_name.strip(), password_hash=hash_password(payload.password))
    db.add(user); db.commit(); db.refresh(user)
    return {"access_token": create_access_token(user.id), "user": user}

@app.post("/api/auth/login", response_model=TokenOut)
def login(payload: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect email or password", headers={"WWW-Authenticate": "Bearer"})
    return {"access_token": create_access_token(user.id), "user": user}

def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)):
    if not credentials:
        raise HTTPException(401, "Authentication required", headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = jwt.decode(credentials.credentials, SECRET, algorithms=[ALGORITHM])
        user_id = int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(401, "Invalid or expired token", headers={"WWW-Authenticate": "Bearer"})
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(401, "User not found")
    return user

@app.get("/api/auth/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user

@app.get("/api/journal", response_model=list[JournalOut])
def list_journal(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return list(db.scalars(select(JournalEntry).where(JournalEntry.owner_id == user.id).order_by(JournalEntry.created_at.desc())))

@app.post("/api/journal", response_model=JournalOut, status_code=201)
def create_journal(payload: JournalIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    entry = JournalEntry(owner_id=user.id, **payload.model_dump())
    db.add(entry); db.commit(); db.refresh(entry)
    return entry

@app.delete("/api/journal/{entry_id}", status_code=204)
def delete_journal(entry_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    entry = db.scalar(select(JournalEntry).where(JournalEntry.id == entry_id, JournalEntry.owner_id == user.id))
    if not entry: raise HTTPException(404, "Journal entry not found")
    db.delete(entry); db.commit()
    return None

@app.get("/api/config")
def public_config():
    return {"registration_open": os.getenv("PUBLIC_REGISTRATION", "true").lower() == "true", "trading_mode": "analysis_only", "risk_guideline_percent": 1, "markets": ["forex", "gold", "crypto", "indices", "stocks"]}


@app.post("/api/analysis/ohlc")
def analyze_market(payload: AnalysisIn, user: User = Depends(current_user)):
    """Analyze supplied OHLC candles. This endpoint does not fetch live data or place orders."""
    try:
        return analyze_ohlc(
            [c.model_dump() for c in payload.candles],
            payload.instrument.strip().upper(),
            payload.timeframe.strip().upper(),
            payload.risk_percent,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

# Live market-data endpoints. These endpoints fetch real provider data only;
# they never fabricate candles when a provider is unavailable.
from fastapi import Query
from .market_data import fetch_candles, provider_status, MarketDataError

@app.get("/api/market/providers")
def market_providers():
    return provider_status()

@app.get("/api/market/candles")
def market_candles(
    market: str = Query(..., description="forex, gold, crypto, indices or stocks"),
    symbol: str = Query(..., min_length=2, max_length=30, description="Provider symbol, e.g. BTCUSDT or EUR/USD"),
    timeframe: str = Query("5M", description="1M, 5M, 15M, 30M, 1H, 4H, 1D or 1W"),
    limit: int = Query(200, ge=50, le=500),
    user: User = Depends(current_user),
):
    try:
        provider, candles = fetch_candles(market, symbol, timeframe, limit)
        return {
            "market": market.lower(), "symbol": symbol.upper(), "timeframe": timeframe.upper(),
            "provider": provider, "data_status": "live", "count": len(candles), "candles": candles,
        }
    except MarketDataError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.post("/api/analysis/chart-image")
async def analyze_chart_screenshot(
    image: UploadFile = File(...),
    instrument: str | None = Form(default=None, max_length=40),
    timeframe: str | None = Form(default=None, max_length=10),
    user: User = Depends(current_user),
):
    """Analyze an uploaded chart image using the configured vision provider. No orders are placed."""
    if image.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=415, detail="Upload a PNG, JPEG, or WEBP chart image.")
    data = await image.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Chart image exceeds the 8 MB limit.")
    if not valid_image(data, image.content_type):
        raise HTTPException(status_code=415, detail="The uploaded file is not a valid supported image.")
    try:
        return await analyze_chart_image(data, image.content_type, instrument, timeframe)
    except RuntimeError as exc:
        message = str(exc)
        if "not configured" in message:
            raise HTTPException(status_code=503, detail=message)
        raise HTTPException(status_code=502, detail=message)
    finally:
        await image.close()


@app.get("/api/admin/overview")
def admin_overview(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Minimal admin metrics. Only accounts explicitly assigned role=admin can access."""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Administrator access required")
    from sqlalchemy import func
    return {"users": db.scalar(select(func.count(User.id))) or 0, "journal_entries": db.scalar(select(func.count(JournalEntry.id))) or 0, "registration_open": os.getenv("PUBLIC_REGISTRATION", "true").lower() == "true"}


# Serve the browser app from the API origin so deployment needs only one public service.
STATIC_DIR = Path(__file__).resolve().parent / "static"
if STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="frontend")
