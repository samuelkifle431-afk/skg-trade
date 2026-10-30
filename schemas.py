from datetime import datetime
from pydantic import BaseModel, EmailStr, Field, ConfigDict

class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    full_name: str = Field(default="", max_length=120)

class LoginIn(BaseModel):
    email: EmailStr
    password: str

class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: EmailStr
    full_name: str
    role: str
    created_at: datetime

class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut

class JournalIn(BaseModel):
    instrument: str = Field(min_length=1, max_length=40)
    direction: str = Field(pattern="^(BUY|SELL|WAIT)$")
    entry_price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    outcome: str = Field(default="planned", pattern="^(planned|win|loss|breakeven|cancelled)$")
    notes: str = Field(default="", max_length=5000)

class JournalOut(JournalIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime


class CandleIn(BaseModel):
    open: float
    high: float
    low: float
    close: float
    volume: float = 0

class AnalysisIn(BaseModel):
    instrument: str = Field(min_length=1, max_length=40)
    timeframe: str = Field(default="1H", max_length=10)
    candles: list[CandleIn] = Field(min_length=50, max_length=500)
    risk_percent: float = Field(default=1.0, gt=0, le=2)
