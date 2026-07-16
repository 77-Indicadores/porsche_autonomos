from __future__ import annotations

import json

from itsdangerous import URLSafeSerializer
from passlib.context import CryptContext


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
MODULOS = ["autonomos", "dho", "facilities", "folha"]
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


def is_admin(request) -> bool:
    user = getattr(request.state, "current_user", None)
    return bool(user and user.get("perfil") == "admin")


def tem_acesso_modulo(request, modulo: str) -> bool:
    """Admin tem acesso a tudo. Operador sem modulos_acesso configurado também acessa tudo (legado)."""
    user = getattr(request.state, "current_user", None)
    if not user:
        return False
    if user.get("perfil") == "admin":
        return True
    raw = user.get("modulos_acesso")
    if not raw or raw == "[]":
        return True
    try:
        modulos = json.loads(raw)
    except Exception:
        return True
    return modulo in modulos

