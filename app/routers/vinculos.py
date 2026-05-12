from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import Autonomo, Cargo, Etapa, Movimentacao, Piloto, Vinculo
from app.template_config import templates
from app.utils import flash_from_request, parse_date, parse_money, redirect_with_message

router = APIRouter(prefix="/vinculos", tags=["vinculos"])


def options(db):
    return {
        "etapas": db.query(Etapa).filter(Etapa.ativo.is_(True)).order_by(Etapa.nome).all(),
        "pilotos": db.query(Piloto).filter(Piloto.ativo.is_(True)).order_by(Piloto.nome).all(),
        "autonomos": db.query(Autonomo).filter(Autonomo.ativo.is_(True)).order_by(Autonomo.nome).all(),
        "cargos": db.query(Cargo).filter(Cargo.ativo.is_(True)).order_by(Cargo.nome).all(),
    }


def active_duplicate(db, etapa_id, piloto_id, autonomo_id, ignore_id=None):
    query = db.query(Vinculo).filter(
        Vinculo.etapa_id == etapa_id,
        Vinculo.piloto_id == piloto_id,
        Vinculo.autonomo_id == autonomo_id,
        Vinculo.status == "ATIVO",
    )
    if ignore_id:
        query = query.filter(Vinculo.id != ignore_id)
    return query.first()


@router.get("")
def index(request: Request, etapa_id: str = "", piloto_id: str = "", autonomo: str = "", status: str = "", db: Session = Depends(get_db)):
    query = db.query(Vinculo).options(joinedload(Vinculo.etapa), joinedload(Vinculo.piloto), joinedload(Vinculo.autonomo), joinedload(Vinculo.cargo))
    if etapa_id:
        query = query.filter(Vinculo.etapa_id == int(etapa_id))
    if piloto_id:
        query = query.filter(Vinculo.piloto_id == int(piloto_id))
    if autonomo:
        query = query.join(Autonomo).filter(Autonomo.nome.ilike(f"%{autonomo}%"))
    if status:
        query = query.filter(Vinculo.status == status)
    vinculos = query.order_by(Vinculo.status, Vinculo.data_inicio.desc()).all()
    return templates.TemplateResponse(
        "vinculos/list.html",
        {"request": request, "vinculos": vinculos, "filtros": {"etapa_id": etapa_id, "piloto_id": piloto_id, "autonomo": autonomo, "status": status}, **options(db), **flash_from_request(request)},
    )


@router.get("/novo")
def novo(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("vinculos/form.html", {"request": request, "vinculo": None, **options(db), **flash_from_request(request)})


@router.post("/novo")
def criar(
    etapa_id: int = Form(...),
    piloto_id: int = Form(...),
    autonomo_id: int = Form(...),
    cargo_id: int = Form(...),
    data_inicio: str = Form(...),
    valor_acordado: str = Form(""),
    observacao: str = Form(""),
    db: Session = Depends(get_db),
):
    if active_duplicate(db, etapa_id, piloto_id, autonomo_id):
        return redirect_with_message("/vinculos/novo", error="Esse autonomo ja tem vinculo ativo para este piloto e etapa.")
    vinculo = Vinculo(etapa_id=etapa_id, piloto_id=piloto_id, autonomo_id=autonomo_id, cargo_id=cargo_id, data_inicio=parse_date(data_inicio), valor_acordado=parse_money(valor_acordado), observacao=observacao)
    db.add(vinculo)
    db.flush()
    db.add(Movimentacao(data_movimentacao=vinculo.data_inicio, tipo="ENTRADA", etapa_id=etapa_id, piloto_id=piloto_id, autonomo_novo_id=autonomo_id, vinculo_novo_id=vinculo.id, cargo_id=cargo_id, observacao=observacao))
    db.commit()
    return redirect_with_message("/vinculos", success="Vinculo criado com movimentacao de entrada.")


@router.get("/{id}/editar")
def editar(id: int, request: Request, db: Session = Depends(get_db)):
    vinculo = db.get(Vinculo, id)
    if not vinculo:
        return redirect_with_message("/vinculos", error="Vinculo nao encontrado.")
    return templates.TemplateResponse("vinculos/form.html", {"request": request, "vinculo": vinculo, **options(db), **flash_from_request(request)})


@router.post("/{id}/editar")
def atualizar(
    id: int,
    etapa_id: int = Form(...),
    piloto_id: int = Form(...),
    autonomo_id: int = Form(...),
    cargo_id: int = Form(...),
    data_inicio: str = Form(...),
    data_fim: str = Form(""),
    status: str = Form("ATIVO"),
    valor_acordado: str = Form(""),
    observacao: str = Form(""),
    db: Session = Depends(get_db),
):
    vinculo = db.get(Vinculo, id)
    if not vinculo:
        return redirect_with_message("/vinculos", error="Vinculo nao encontrado.")
    if status == "ATIVO" and active_duplicate(db, etapa_id, piloto_id, autonomo_id, ignore_id=id):
        return redirect_with_message(f"/vinculos/{id}/editar", error="Esse autonomo ja tem vinculo ativo para este piloto e etapa.")
    vinculo.etapa_id = etapa_id
    vinculo.piloto_id = piloto_id
    vinculo.autonomo_id = autonomo_id
    vinculo.cargo_id = cargo_id
    vinculo.data_inicio = parse_date(data_inicio)
    vinculo.data_fim = parse_date(data_fim)
    vinculo.status = status
    vinculo.valor_acordado = parse_money(valor_acordado)
    vinculo.observacao = observacao
    db.add(Movimentacao(tipo="ALTERACAO", etapa_id=etapa_id, piloto_id=piloto_id, autonomo_novo_id=autonomo_id, vinculo_novo_id=id, cargo_id=cargo_id, observacao="Vinculo atualizado."))
    db.commit()
    return redirect_with_message("/vinculos", success="Vinculo atualizado com sucesso.")


@router.post("/{id}/encerrar")
def encerrar(id: int, data_fim: str = Form(...), motivo: str = Form(...), observacao: str = Form(""), db: Session = Depends(get_db)):
    vinculo = db.get(Vinculo, id)
    if not vinculo or vinculo.status != "ATIVO":
        return redirect_with_message("/vinculos", error="Somente vinculos ativos podem ser encerrados.")
    fim = parse_date(data_fim)
    vinculo.status = "ENCERRADO"
    vinculo.data_fim = fim
    db.add(Movimentacao(data_movimentacao=fim, tipo="SAIDA", etapa_id=vinculo.etapa_id, piloto_id=vinculo.piloto_id, autonomo_anterior_id=vinculo.autonomo_id, vinculo_anterior_id=vinculo.id, cargo_id=vinculo.cargo_id, motivo=motivo, observacao=observacao))
    db.commit()
    return redirect_with_message("/vinculos", success="Vinculo encerrado com sucesso.")
