from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Piloto
from app.template_config import templates
from app.utils import flash_from_request, is_active, redirect_with_message

router = APIRouter(prefix="/pilotos", tags=["pilotos"])


@router.get("")
def index(request: Request, db: Session = Depends(get_db)):
    pilotos = db.query(Piloto).order_by(Piloto.nome).all()
    return templates.TemplateResponse("pilotos/list.html", {"request": request, "pilotos": pilotos, **flash_from_request(request)})


@router.get("/novo")
def novo(request: Request):
    return templates.TemplateResponse("pilotos/form.html", {"request": request, "piloto": None, **flash_from_request(request)})


@router.post("/novo")
def criar(nome: str = Form(...), categoria: str = Form(""), ativo: str | None = Form(None), db: Session = Depends(get_db)):
    db.add(Piloto(nome=nome, categoria=categoria, ativo=is_active(ativo)))
    db.commit()
    return redirect_with_message("/pilotos", success="Piloto cadastrado com sucesso.")


@router.get("/{id}/editar")
def editar(id: int, request: Request, db: Session = Depends(get_db)):
    piloto = db.get(Piloto, id)
    if not piloto:
        return redirect_with_message("/pilotos", error="Piloto nao encontrado.")
    return templates.TemplateResponse("pilotos/form.html", {"request": request, "piloto": piloto, **flash_from_request(request)})


@router.post("/{id}/editar")
def atualizar(id: int, nome: str = Form(...), categoria: str = Form(""), ativo: str | None = Form(None), db: Session = Depends(get_db)):
    piloto = db.get(Piloto, id)
    if not piloto:
        return redirect_with_message("/pilotos", error="Piloto nao encontrado.")
    piloto.nome = nome
    piloto.categoria = categoria
    piloto.ativo = is_active(ativo)
    db.commit()
    return redirect_with_message("/pilotos", success="Piloto atualizado com sucesso.")


@router.post("/{id}/toggle")
def toggle(id: int, db: Session = Depends(get_db)):
    piloto = db.get(Piloto, id)
    if not piloto:
        return redirect_with_message("/pilotos", error="Piloto nao encontrado.")
    piloto.ativo = not piloto.ativo
    db.commit()
    return redirect_with_message("/pilotos", success="Status do piloto atualizado.")
