from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import hash_password
from app.database import get_db
from app.models import Usuario
from app.template_config import templates


router = APIRouter(prefix="/usuarios", tags=["usuarios"])


def require_admin(request: Request):
    user = getattr(request.state, "current_user", None)
    if not user or user.get("perfil") != "admin":
        return False
    return True


@router.get("")
def list_users(request: Request, db: Session = Depends(get_db)):
    if not require_admin(request):
        return RedirectResponse("/auth/login?erro=permissao", status_code=303)
    usuarios = db.query(Usuario).order_by(Usuario.nome.asc()).all()
    return templates.TemplateResponse("usuarios/list.html", {"request": request, "usuarios": usuarios})


@router.get("/novo")
def new_user_page(request: Request):
    if not require_admin(request):
        return RedirectResponse("/auth/login?erro=permissao", status_code=303)
    return templates.TemplateResponse("usuarios/form.html", {"request": request, "usuario": None})


@router.post("/novo")
def create_user(
    request: Request,
    nome: str = Form(...),
    email: str = Form(...),
    senha: str = Form(...),
    perfil: str = Form("operador"),
    db: Session = Depends(get_db),
):
    if not require_admin(request):
        return RedirectResponse("/auth/login?erro=permissao", status_code=303)

    exists = db.query(Usuario).filter(Usuario.email == email).first()
    if exists:
        return templates.TemplateResponse(
            "usuarios/form.html",
            {"request": request, "usuario": None, "error": "Email ja cadastrado"},
            status_code=400,
        )

    db.add(Usuario(nome=nome, email=email, senha_hash=hash_password(senha), perfil=perfil, ativo="Sim"))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return templates.TemplateResponse(
            "usuarios/form.html",
            {"request": request, "usuario": None, "error": "Email ja cadastrado"},
            status_code=400,
        )
    return RedirectResponse("/usuarios", status_code=303)

