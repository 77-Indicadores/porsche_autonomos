import json
import secrets
from typing import List

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import acesso_email
from app.auth import hash_password, MODULOS
from app.database import get_db
from app.models import Usuario
from app.template_config import templates
from app.utils import flash_from_request, redirect_with_message


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
    return templates.TemplateResponse("usuarios/list.html",
        {"request": request, "usuarios": usuarios,
         "smtp_ok": acesso_email.smtp_configurado(),
         **flash_from_request(request)})


@router.get("/novo")
def new_user_page(request: Request):
    if not require_admin(request):
        return RedirectResponse("/auth/login?erro=permissao", status_code=303)
    return templates.TemplateResponse("usuarios/form.html",
        {"request": request, "usuario": None, "modulos": MODULOS,
         "smtp_ok": acesso_email.smtp_configurado()})


@router.post("/novo")
def create_user(
    request: Request,
    nome: str = Form(...),
    email: str = Form(...),
    senha: str = Form(""),
    perfil: str = Form("operador"),
    modulos: List[str] = Form(default=[]),
    db: Session = Depends(get_db),
):
    """Cria a conta e convida a pessoa por e-mail a definir a própria senha.

    Antes o admin digitava uma senha aqui e a combinava com a pessoa por fora,
    normalmente no WhatsApp: a senha ficava registrada na conversa, quem criou
    a conhecia e ninguém era obrigado a trocá-la. Agora ela vai por link e só a
    própria pessoa define — o campo de senha continua aceito para quando não há
    SMTP configurado, mas não é mais o caminho normal.
    """
    if not require_admin(request):
        return RedirectResponse("/auth/login?erro=permissao", status_code=303)

    exists = db.query(Usuario).filter(Usuario.email == email).first()
    if exists:
        return templates.TemplateResponse(
            "usuarios/form.html",
            {"request": request, "usuario": None, "modulos": MODULOS,
             "smtp_ok": acesso_email.smtp_configurado(),
             "error": "Email ja cadastrado"},
            status_code=400,
        )

    modulos_json = json.dumps(modulos) if perfil != "admin" else json.dumps(MODULOS)
    convidar = acesso_email.smtp_configurado() and not senha

    # Sem senha definida, a conta nasce INATIVA: conta ativa com senha
    # aleatória que ninguém conhece é porta aberta esperando ser descoberta.
    # O primeiro acesso pelo link é que a ativa.
    senha_inicial = senha or secrets.token_urlsafe(32)
    db.add(Usuario(nome=nome, email=email, senha_hash=hash_password(senha_inicial),
                   perfil=perfil, ativo="Nao" if convidar else "Sim",
                   modulos_acesso=modulos_json))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return templates.TemplateResponse(
            "usuarios/form.html",
            {"request": request, "usuario": None, "modulos": MODULOS,
             "smtp_ok": acesso_email.smtp_configurado(),
             "error": "Email ja cadastrado"},
            status_code=400,
        )

    if not convidar:
        if not acesso_email.smtp_configurado():
            return redirect_with_message(
                "/usuarios",
                error="Usuário criado, mas o envio de e-mail não está configurado "
                      "(SMTP_HOST). Combine a senha com a pessoa por outro meio e "
                      "peça que ela troque no primeiro acesso.")
        return RedirectResponse("/usuarios", status_code=303)

    try:
        token = acesso_email.gerar_token(email, "criacao")
        link = f"{acesso_email.url_base(request)}/auth/definir-senha?token={token}"
        acesso_email.enviar_convite(email, nome, link)
    except Exception as exc:
        # A conta fica criada e inativa: refazer o cadastro daria "e-mail já
        # cadastrado" e ninguém entenderia. O reenvio resolve.
        return redirect_with_message(
            "/usuarios",
            error=f"Usuário criado, mas não consegui enviar o convite: {exc} — "
                  f"use 'Reenviar acesso' na lista quando o e-mail voltar.")

    return redirect_with_message(
        "/usuarios",
        success=f"Usuário criado. Convite enviado para {email} — a conta é ativada "
                f"quando a pessoa definir a senha.")


@router.post("/{id_usuario}/reenviar-acesso")
def resend_access(id_usuario: int, request: Request, db: Session = Depends(get_db)):
    """Manda de novo o link de senha: convite perdido, vencido ou senha esquecida."""
    if not require_admin(request):
        return RedirectResponse("/auth/login?erro=permissao", status_code=303)

    user = db.query(Usuario).filter(Usuario.id_usuario == id_usuario).first()
    if not user:
        return redirect_with_message("/usuarios", error="Usuário não encontrado.")
    if not acesso_email.smtp_configurado():
        return redirect_with_message(
            "/usuarios",
            error="Envio de e-mail não configurado (SMTP_HOST).")

    motivo = "criacao" if user.ativo != "Sim" else "recuperacao"
    try:
        token = acesso_email.gerar_token(user.email, motivo)
        link = f"{acesso_email.url_base(request)}/auth/definir-senha?token={token}"
        if motivo == "criacao":
            acesso_email.enviar_convite(user.email, user.nome, link)
        else:
            acesso_email.enviar_recuperacao(user.email, user.nome, link)
    except Exception as exc:
        return redirect_with_message("/usuarios", error=f"Não consegui enviar: {exc}")

    return redirect_with_message("/usuarios", success=f"Link enviado para {user.email}.")


@router.get("/{id_usuario}/editar")
def edit_user_page(id_usuario: int, request: Request, db: Session = Depends(get_db)):
    if not require_admin(request):
        return RedirectResponse("/auth/login?erro=permissao", status_code=303)
    usuario = db.get(Usuario, id_usuario)
    if not usuario:
        return RedirectResponse("/usuarios", status_code=303)
    return templates.TemplateResponse("usuarios/form.html",
        {"request": request, "usuario": usuario, "modulos": MODULOS,
         "smtp_ok": acesso_email.smtp_configurado()})


@router.post("/{id_usuario}/editar")
def update_user(
    id_usuario: int,
    request: Request,
    nome: str = Form(...),
    email: str = Form(...),
    senha: str = Form(""),
    perfil: str = Form("operador"),
    modulos: List[str] = Form(default=[]),
    db: Session = Depends(get_db),
):
    if not require_admin(request):
        return RedirectResponse("/auth/login?erro=permissao", status_code=303)

    usuario = db.get(Usuario, id_usuario)
    if not usuario:
        return RedirectResponse("/usuarios", status_code=303)

    exists = db.query(Usuario).filter(Usuario.email == email, Usuario.id_usuario != id_usuario).first()
    if exists:
        return templates.TemplateResponse(
            "usuarios/form.html",
            {"request": request, "usuario": usuario, "modulos": MODULOS, "error": "Email ja cadastrado"},
            status_code=400,
        )

    usuario.nome = nome
    usuario.email = email
    usuario.perfil = perfil
    usuario.modulos_acesso = json.dumps(MODULOS) if perfil == "admin" else json.dumps(modulos)
    if senha:
        usuario.senha_hash = hash_password(senha)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return templates.TemplateResponse(
            "usuarios/form.html",
            {"request": request, "usuario": usuario, "error": "Email ja cadastrado"},
            status_code=400,
        )
    return RedirectResponse("/usuarios", status_code=303)


@router.post("/{id_usuario}/toggle-ativo")
def toggle_user_active(id_usuario: int, request: Request, db: Session = Depends(get_db)):
    if not require_admin(request):
        return RedirectResponse("/auth/login?erro=permissao", status_code=303)
    usuario = db.get(Usuario, id_usuario)
    if not usuario:
        return RedirectResponse("/usuarios", status_code=303)
    usuario.ativo = "Nao" if usuario.ativo == "Sim" else "Sim"
    db.commit()
    return RedirectResponse("/usuarios", status_code=303)

