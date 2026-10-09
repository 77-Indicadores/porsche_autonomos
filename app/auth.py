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


def dados_atuais_usuario(id_usuario=None, email: str = "") -> dict | None:
    """Perfil, módulos e ativo direto do banco, para reconciliar a sessão.

    O cookie guarda esses campos congelados no momento do login: mudar o
    perfil ou liberar um módulo não surtia efeito até a pessoa deslogar — e
    desativar um usuário não o tirava do sistema.

    A busca é pelo id_usuario, que é o que o token de login carrega (o token
    NÃO tem e-mail — buscar por e-mail matava a sessão de todo mundo e
    trancava o login num loop). None significa "usuário sumiu do banco";
    {} significa "não deu para verificar" e mantém a sessão do cookie.
    """
    try:
        from sqlalchemy import text
        from app.database import engine
        if id_usuario:
            sql, params = ("SELECT perfil, modulos_acesso, ativo FROM usuarios "
                           "WHERE id_usuario = :i"), {"i": int(id_usuario)}
        elif email:
            sql, params = ("SELECT perfil, modulos_acesso, ativo FROM usuarios "
                           "WHERE email = :e"), {"e": email}
        else:
            return {}  # sessão sem identificador: não dá para verificar
        with engine.connect() as conn:
            row = conn.execute(text(sql), params).mappings().first()
        return dict(row) if row else None
    except Exception as exc:
        print(f"AVISO - não consegui atualizar dados do usuário: {exc}")
        return {}


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

