from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Etapa
from app.template_config import templates
from app.utils import flash_from_request, is_active, parse_date, redirect_with_message

router = APIRouter(prefix="/etapas", tags=["etapas"])


@router.get("")
def index(request: Request, db: Session = Depends(get_db)):
    etapas = db.query(Etapa).order_by(Etapa.temporada.desc(), Etapa.data_inicio.desc()).all()
    return templates.TemplateResponse("etapas/list.html", {"request": request, "etapas": etapas, **flash_from_request(request)})


@router.get("/novo")
def novo(request: Request):
    return templates.TemplateResponse("etapas/form.html", {"request": request, "etapa": None, **flash_from_request(request)})


@router.post("/novo")
def criar(
    nome: str = Form(...),
    local: str = Form(""),
    data_inicio: str = Form(""),
    data_fim: str = Form(""),
    temporada: str = Form(""),
    ativo: str | None = Form(None),
    db: Session = Depends(get_db),
):
    db.add(Etapa(nome=nome, local=local, data_inicio=parse_date(data_inicio), data_fim=parse_date(data_fim), temporada=temporada, ativo=is_active(ativo)))
    db.commit()
    return redirect_with_message("/etapas", success="Etapa cadastrada com sucesso.")


@router.get("/{id}/editar")
def editar(id: int, request: Request, db: Session = Depends(get_db)):
    etapa = db.get(Etapa, id)
    if not etapa:
        return redirect_with_message("/etapas", error="Etapa nao encontrada.")
    return templates.TemplateResponse("etapas/form.html", {"request": request, "etapa": etapa, **flash_from_request(request)})


@router.post("/{id}/editar")
def atualizar(
    id: int,
    nome: str = Form(...),
    local: str = Form(""),
    data_inicio: str = Form(""),
    data_fim: str = Form(""),
    temporada: str = Form(""),
    ativo: str | None = Form(None),
    db: Session = Depends(get_db),
):
    etapa = db.get(Etapa, id)
    if not etapa:
        return redirect_with_message("/etapas", error="Etapa nao encontrada.")
    etapa.nome = nome
    etapa.local = local
    etapa.data_inicio = parse_date(data_inicio)
    etapa.data_fim = parse_date(data_fim)
    etapa.temporada = temporada
    etapa.ativo = is_active(ativo)
    db.commit()
    return redirect_with_message("/etapas", success="Etapa atualizada com sucesso.")


@router.post("/{id}/toggle")
def toggle(id: int, db: Session = Depends(get_db)):
    etapa = db.get(Etapa, id)
    if not etapa:
        return redirect_with_message("/etapas", error="Etapa nao encontrada.")
    etapa.ativo = not etapa.ativo
    db.commit()
    return redirect_with_message("/etapas", success="Status da etapa atualizado.")
