from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Cargo
from app.template_config import templates
from app.utils import flash_from_request, is_active, redirect_with_message

router = APIRouter(prefix="/cargos", tags=["cargos"])


@router.get("")
def index(request: Request, db: Session = Depends(get_db)):
    cargos = db.query(Cargo).order_by(Cargo.nome).all()
    return templates.TemplateResponse("cargos/list.html", {"request": request, "cargos": cargos, **flash_from_request(request)})


@router.get("/novo")
def novo(request: Request):
    return templates.TemplateResponse("cargos/form.html", {"request": request, "cargo": None, **flash_from_request(request)})


@router.post("/novo")
def criar(nome: str = Form(...), ativo: str | None = Form(None), db: Session = Depends(get_db)):
    db.add(Cargo(nome=nome, ativo=is_active(ativo)))
    db.commit()
    return redirect_with_message("/cargos", success="Cargo cadastrado com sucesso.")


@router.get("/{id}/editar")
def editar(id: int, request: Request, db: Session = Depends(get_db)):
    cargo = db.get(Cargo, id)
    if not cargo:
        return redirect_with_message("/cargos", error="Cargo nao encontrado.")
    return templates.TemplateResponse("cargos/form.html", {"request": request, "cargo": cargo, **flash_from_request(request)})


@router.post("/{id}/editar")
def atualizar(id: int, nome: str = Form(...), ativo: str | None = Form(None), db: Session = Depends(get_db)):
    cargo = db.get(Cargo, id)
    if not cargo:
        return redirect_with_message("/cargos", error="Cargo nao encontrado.")
    cargo.nome = nome
    cargo.ativo = is_active(ativo)
    db.commit()
    return redirect_with_message("/cargos", success="Cargo atualizado com sucesso.")


@router.post("/{id}/toggle")
def toggle(id: int, db: Session = Depends(get_db)):
    cargo = db.get(Cargo, id)
    if not cargo:
        return redirect_with_message("/cargos", error="Cargo nao encontrado.")
    cargo.ativo = not cargo.ativo
    db.commit()
    return redirect_with_message("/cargos", success="Status do cargo atualizado.")
