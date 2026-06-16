from __future__ import annotations

from itsdangerous import URLSafeSerializer
from passlib.context import CryptContext


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SESSION_COOKIE = "porsche_session"
SESSION_SECRET = "change-this-in-production"
serializer = URLSafeSerializer(SESSION_SECRET, salt="auth")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    return pwd_context.verify(password, hashed_password)


def create_session_token(payload: dict[str, str]) -> str:
    return serializer.dumps(payload)


def read_session_token(token: str) -> dict[str, str] | None:
    try:
        return serializer.loads(token)
    except Exception:
        return None

