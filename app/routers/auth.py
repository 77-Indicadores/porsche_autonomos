from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth import SESSION_COOKIE, create_session_token, verify_password
from app.database import get_db
from app.models import Usuario
from app.template_config import templates


router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/login")
def login_page(request: Request, erro: int = 0):
    return templates.TemplateResponse("auth/login.html", {"request": request, "erro": erro})


@router.post("/login")
def login(email: str = Form(...), senha: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(Usuario).filter(Usuario.email == email, Usuario.ativo == "Sim").first()
    if not user or not verify_password(senha, user.senha_hash):
        return RedirectResponse("/auth/login?erro=1", status_code=303)

    response = RedirectResponse("/", status_code=303)
    token = create_session_token({
        "id_usuario": str(user.id_usuario),
        "perfil": user.perfil,
        "nome": user.nome,
        "modulos_acesso": user.modulos_acesso or "[]",
    })
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax", path="/")
    return response


@router.post("/logout")
def logout():
    response = RedirectResponse("/auth/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response

