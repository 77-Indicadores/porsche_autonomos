from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app import acesso_email
from app.auth import (SESSION_COOKIE, create_session_token,
                      hash_password, verify_password)
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



# ─── primeiro acesso e recuperação de senha ───────────────────────────────────

def _tela_senha(request, token: str, registro: dict | None,
                erro: str = "", status: int = 200):
    return templates.TemplateResponse(
        "auth/definir_senha.html",
        {
            "request": request,
            "token": token,
            "valido": bool(registro),
            "email": registro["email"] if registro else "",
            "motivo": registro["motivo"] if registro else "",
            "erro": erro,
        },
        status_code=status,
    )


@router.get("/definir-senha")
def definir_senha_page(request: Request, token: str = ""):
    return _tela_senha(request, token, acesso_email.validar_token(token))


@router.post("/definir-senha")
def definir_senha(request: Request, token: str = Form(""), senha: str = Form(""),
                  confirmacao: str = Form(""), db: Session = Depends(get_db)):
    registro = acesso_email.validar_token(token)
    if not registro:
        return _tela_senha(request, token, None, status=400)

    if len(senha) < 8:
        return _tela_senha(request, token, registro,
                           erro="A senha precisa ter pelo menos 8 caracteres.",
                           status=400)
    if senha != confirmacao:
        return _tela_senha(request, token, registro,
                           erro="As duas senhas não são iguais.", status=400)

    user = db.query(Usuario).filter(Usuario.email == registro["email"]).first()
    if not user:
        # a conta sumiu entre o convite e o clique
        return _tela_senha(request, token, None, status=400)

    user.senha_hash = hash_password(senha)
    # Primeiro acesso concluído também ativa a conta: ela nasce inativa para
    # não existir conta com senha que ninguém definiu esperando ser usada.
    if registro["motivo"] == "criacao":
        user.ativo = "Sim"
    db.commit()
    acesso_email.marcar_usado(token)

    # entra direto: pedir para digitar de novo a senha recém-criada não
    # protege nada e só adiciona um passo
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        SESSION_COOKIE,
        create_session_token({
            "id_usuario": str(user.id_usuario),
            "perfil": user.perfil,
            "nome": user.nome,
            "modulos_acesso": user.modulos_acesso or "[]",
        }),
        httponly=True, samesite="lax", path="/")
    return response
