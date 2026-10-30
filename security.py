import hashlib, hmac, os
from datetime import datetime, timedelta, timezone
from jose import jwt

ALGORITHM = "HS256"
SECRET = os.getenv("JWT_SECRET", "DEV_ONLY_CHANGE_THIS_SECRET_BEFORE_DEPLOYMENT")
if os.getenv("APP_ENV", "development").lower() == "production" and (SECRET == "DEV_ONLY_CHANGE_THIS_SECRET_BEFORE_DEPLOYMENT" or len(SECRET) < 32):
    raise RuntimeError("Set a unique JWT_SECRET of at least 32 characters before production deployment.")

def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
    return f"pbkdf2_sha256${salt.hex()}${digest.hex()}"

def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_hex, digest_hex = stored.split("$")
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), 310_000)
        return hmac.compare_digest(actual.hex(), digest_hex)
    except (ValueError, TypeError):
        return False

def create_access_token(user_id: int) -> str:
    expires = datetime.now(timezone.utc) + timedelta(minutes=int(os.getenv("JWT_EXPIRE_MINUTES", "1440")))
    return jwt.encode({"sub": str(user_id), "exp": expires}, SECRET, algorithm=ALGORITHM)
