from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import Autonomo, Cargo, Etapa, Movimentacao, Piloto, Vinculo
from app.routers.vinculos import active_duplicate, options
from app.template_config import templates
from app.utils import flash_from_request, parse_date, parse_money, redirect_with_message

router = APIRouter(prefix="/movimentacoes", tags=["movimentacoes"])


@router.get("")
def index(
    request: Request,
    data_inicial: str = "",
    data_final: str = "",
    tipo: str = "",
    etapa_id: str = "",
    piloto_id: str = "",
    autonomo: str = "",
    db: Session = Depends(get_db),
):
    query = db.query(Movimentacao).options(
        joinedload(Movimentacao.etapa),
        joinedload(Movimentacao.piloto),
        joinedload(Movimentacao.autonomo_anterior),
        joinedload(Movimentacao.autonomo_novo),
    )
    if data_inicial:
        query = query.filter(Movimentacao.data_movimentacao >= parse_date(data_inicial))
    if data_final:
        query = query.filter(Movimentacao.data_movimentacao <= parse_date(data_final))
    if tipo:
        query = query.filter(Movimentacao.tipo == tipo)
    if etapa_id:
        query = query.filter(Movimentacao.etapa_id == int(etapa_id))
    if piloto_id:
        query = query.filter(Movimentacao.piloto_id == int(piloto_id))
    if autonomo:
        ids = [a.id for a in db.query(Autonomo).filter(Autonomo.nome.ilike(f"%{autonomo}%")).all()]
        query = query.filter(or_(Movimentacao.autonomo_anterior_id.in_(ids), Movimentacao.autonomo_novo_id.in_(ids)))
    movimentacoes = query.order_by(Movimentacao.data_movimentacao.desc(), Movimentacao.id.desc()).all()
    return templates.TemplateResponse(
        "movimentacoes/list.html",
        {
            "request": request,
            "movimentacoes": movimentacoes,
            "filtros": {"data_inicial": data_inicial, "data_final": data_final, "tipo": tipo, "etapa_id": etapa_id, "piloto_id": piloto_id, "autonomo": autonomo},
            **options(db),
            **flash_from_request(request),
        },
    )


@router.get("/entrada")
def entrada_form(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("movimentacoes/entrada.html", {"request": request, "today": date.today(), **options(db), **flash_from_request(request)})


@router.post("/entrada")
def entrada(
    data_movimentacao: str = Form(...),
    etapa_id: int = Form(...),
    piloto_id: int = Form(...),
    autonomo_id: int = Form(...),
    cargo_id: int = Form(...),
    valor_acordado: str = Form(""),
    observacao: str = Form(""),
    db: Session = Depends(get_db),
):
    if active_duplicate(db, etapa_id, piloto_id, autonomo_id):
        return redirect_with_message("/movimentacoes/entrada", error="Esse autonomo ja tem vinculo ativo para este piloto e etapa.")
    data = parse_date(data_movimentacao)
    vinculo = Vinculo(etapa_id=etapa_id, piloto_id=piloto_id, autonomo_id=autonomo_id, cargo_id=cargo_id, data_inicio=data, status="ATIVO", valor_acordado=parse_money(valor_acordado), observacao=observacao)
    db.add(vinculo)
    db.flush()
    db.add(Movimentacao(data_movimentacao=data, tipo="ENTRADA", etapa_id=etapa_id, piloto_id=piloto_id, autonomo_novo_id=autonomo_id, vinculo_novo_id=vinculo.id, cargo_id=cargo_id, observacao=observacao))
    db.commit()
    return redirect_with_message("/movimentacoes", success="Entrada registrada com sucesso.")


@router.get("/saida")
def saida_form(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("movimentacoes/saida.html", {"request": request, "today": date.today(), **options(db), **flash_from_request(request)})


@router.post("/saida")
def saida(
    data_movimentacao: str = Form(...),
    etapa_id: int = Form(...),
    piloto_id: int = Form(...),
    autonomo_id: int = Form(...),
    motivo: str = Form(...),
    observacao: str = Form(""),
    db: Session = Depends(get_db),
):
    vinculo = (
        db.query(Vinculo)
        .filter(Vinculo.etapa_id == etapa_id, Vinculo.piloto_id == piloto_id, Vinculo.autonomo_id == autonomo_id, Vinculo.status == "ATIVO")
        .first()
    )
    if not vinculo:
        return redirect_with_message("/movimentacoes/saida", error="Nao existe vinculo ativo para esse autonomo, piloto e etapa.")
    data = parse_date(data_movimentacao)
    vinculo.data_fim = data
    vinculo.status = "ENCERRADO"
    db.add(Movimentacao(data_movimentacao=data, tipo="SAIDA", etapa_id=etapa_id, piloto_id=piloto_id, autonomo_anterior_id=autonomo_id, vinculo_anterior_id=vinculo.id, cargo_id=vinculo.cargo_id, motivo=motivo, observacao=observacao))
    db.commit()
    return redirect_with_message("/movimentacoes", success="Saida registrada com sucesso.")


@router.get("/substituicao")
def substituicao_form(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("movimentacoes/substituicao.html", {"request": request, "today": date.today(), **options(db), **flash_from_request(request)})


@router.post("/substituicao")
def substituicao(
    data_movimentacao: str = Form(...),
    etapa_id: int = Form(...),
    piloto_id: int = Form(...),
    autonomo_anterior_id: int = Form(...),
    autonomo_novo_id: int = Form(...),
    cargo_id: int = Form(...),
    valor_acordado: str = Form(""),
    motivo: str = Form(...),
    observacao: str = Form(""),
    db: Session = Depends(get_db),
):
    if autonomo_anterior_id == autonomo_novo_id:
        return redirect_with_message("/movimentacoes/substituicao", error="O autonomo novo deve ser diferente do anterior.")
    anterior = (
        db.query(Vinculo)
        .filter(Vinculo.etapa_id == etapa_id, Vinculo.piloto_id == piloto_id, Vinculo.autonomo_id == autonomo_anterior_id, Vinculo.status == "ATIVO")
        .first()
    )
    if not anterior:
        return redirect_with_message("/movimentacoes/substituicao", error="O autonomo anterior nao possui vinculo ativo.")
    if active_duplicate(db, etapa_id, piloto_id, autonomo_novo_id):
        return redirect_with_message("/movimentacoes/substituicao", error="O autonomo novo ja tem vinculo ativo para este piloto e etapa.")
    data = parse_date(data_movimentacao)
    anterior.data_fim = data
    anterior.status = "SUBSTITUIDO"
    novo = Vinculo(etapa_id=etapa_id, piloto_id=piloto_id, autonomo_id=autonomo_novo_id, cargo_id=cargo_id, data_inicio=data, status="ATIVO", valor_acordado=parse_money(valor_acordado), observacao=observacao)
    db.add(novo)
    db.flush()
    db.add(
        Movimentacao(
            data_movimentacao=data,
            tipo="SUBSTITUICAO",
            etapa_id=etapa_id,
            piloto_id=piloto_id,
            autonomo_anterior_id=autonomo_anterior_id,
            autonomo_novo_id=autonomo_novo_id,
            vinculo_anterior_id=anterior.id,
            vinculo_novo_id=novo.id,
            cargo_id=cargo_id,
            motivo=motivo,
            observacao=observacao,
        )
    )
    db.commit()
    return redirect_with_message("/movimentacoes", success="Substituicao registrada com sucesso.")
