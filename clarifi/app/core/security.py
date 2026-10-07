from datetime import datetime, timedelta, timezone
import hashlib
import secrets
import uuid

import bcrypt
import jwt
from cryptography.fernet import Fernet

from app.core.config import Settings
from app.core.errors import AppError


def hash_secret(value: str) -> str:
    return bcrypt.hashpw(value.encode(), bcrypt.gensalt()).decode()


def verify_secret(value: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(value.encode(), hashed.encode())
    except (ValueError, TypeError):
        return False


def encrypt_secret(value: str, key: str) -> str:
    return Fernet(key.encode()).encrypt(value.encode()).decode()


def decrypt_secret(value: str, key: str) -> str:
    return Fernet(key.encode()).decrypt(value.encode()).decode()


def create_access_token(user_id: str, settings: Settings) -> tuple[str, str, datetime]:
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=settings.jwt_expires_minutes)
    jti = str(uuid.uuid4())
    token = jwt.encode({"sub": user_id, "iat": now, "exp": expires, "jti": jti}, settings.jwt_secret, algorithm="HS256")
    return token, jti, expires


def decode_access_token(token: str, settings: Settings) -> dict:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise AppError("UNAUTHORIZED", "Invalid or expired access token.", 401) from exc


def new_reset_token() -> str:
    return secrets.token_urlsafe(32)


def stable_reference(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:12].upper()

