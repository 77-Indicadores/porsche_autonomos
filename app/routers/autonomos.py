from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import Autonomo, Cargo, Movimentacao, Vinculo
from app.template_config import templates
from app.utils import flash_from_request, is_active, parse_date, parse_money, redirect_with_message

router = APIRouter(prefix="/autonomos", tags=["autonomos"])


def form_options(db):
    return {"cargos": db.query(Cargo).filter(Cargo.ativo.is_(True)).order_by(Cargo.nome).all()}


@router.get("")
def index(request: Request, nome: str = "", cargo_id: str = "", status: str = "", db: Session = Depends(get_db)):
    query = db.query(Autonomo).options(joinedload(Autonomo.cargo))
    if nome:
        query = query.filter(Autonomo.nome.ilike(f"%{nome}%"))
    if cargo_id:
        query = query.filter(Autonomo.cargo_id == int(cargo_id))
    if status == "ativo":
        query = query.filter(Autonomo.ativo.is_(True))
    elif status == "inativo":
        query = query.filter(Autonomo.ativo.is_(False))
    autonomos = query.order_by(Autonomo.nome).all()
    return templates.TemplateResponse(
        "autonomos/list.html",
        {"request": request, "autonomos": autonomos, "filtros": {"nome": nome, "cargo_id": cargo_id, "status": status}, **form_options(db), **flash_from_request(request)},
    )


@router.get("/novo")
def novo(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("autonomos/form.html", {"request": request, "autonomo": None, **form_options(db), **flash_from_request(request)})


@router.post("/novo")
def criar(
    nome: str = Form(...),
    cargo_id: str = Form(""),
    telefone: str = Form(""),
    email: str = Form(""),
    documento: str = Form(""),
    valor_padrao: str = Form(""),
    ativo: str | None = Form(None),
    observacao: str = Form(""),
    db: Session = Depends(get_db),
):
    db.add(
        Autonomo(
            nome=nome,
            cargo_id=int(cargo_id) if cargo_id else None,
            telefone=telefone,
            email=email,
            documento=documento,
            valor_padrao=parse_money(valor_padrao),
            ativo=is_active(ativo),
            observacao=observacao,
        )
    )
    db.commit()
    return redirect_with_message("/autonomos", success="Autonomo cadastrado com sucesso.")


@router.get("/{id}/editar")
def editar(id: int, request: Request, db: Session = Depends(get_db)):
    autonomo = db.get(Autonomo, id)
    if not autonomo:
        return redirect_with_message("/autonomos", error="Autonomo nao encontrado.")
    return templates.TemplateResponse("autonomos/form.html", {"request": request, "autonomo": autonomo, **form_options(db), **flash_from_request(request)})


@router.post("/{id}/editar")
def atualizar(
    id: int,
    nome: str = Form(...),
    cargo_id: str = Form(""),
    telefone: str = Form(""),
    email: str = Form(""),
    documento: str = Form(""),
    valor_padrao: str = Form(""),
    ativo: str | None = Form(None),
    observacao: str = Form(""),
    db: Session = Depends(get_db),
):
    autonomo = db.get(Autonomo, id)
    if not autonomo:
        return redirect_with_message("/autonomos", error="Autonomo nao encontrado.")
    autonomo.nome = nome
    autonomo.cargo_id = int(cargo_id) if cargo_id else None
    autonomo.telefone = telefone
    autonomo.email = email
    autonomo.documento = documento
    autonomo.valor_padrao = parse_money(valor_padrao)
    autonomo.ativo = is_active(ativo)
    autonomo.observacao = observacao
    db.add(Movimentacao(tipo="ALTERACAO", autonomo_novo_id=autonomo.id, cargo_id=autonomo.cargo_id, observacao="Cadastro do autonomo atualizado."))
    db.commit()
    return redirect_with_message("/autonomos", success="Autonomo atualizado com sucesso.")


@router.post("/{id}/inativar")
def inativar(id: int, data_saida: str = Form(...), motivo_saida: str = Form(...), observacao: str = Form(""), db: Session = Depends(get_db)):
    autonomo = db.get(Autonomo, id)
    if not autonomo:
        return redirect_with_message("/autonomos", error="Autonomo nao encontrado.")
    saida = parse_date(data_saida)
    autonomo.ativo = False
    autonomo.data_saida = saida
    autonomo.motivo_saida = motivo_saida
    if observacao:
        autonomo.observacao = observacao

    ativos = db.query(Vinculo).filter(Vinculo.autonomo_id == id, Vinculo.status == "ATIVO").all()
    for vinculo in ativos:
        vinculo.status = "ENCERRADO"
        vinculo.data_fim = saida
        db.add(
            Movimentacao(
                data_movimentacao=saida,
                tipo="SAIDA",
                etapa_id=vinculo.etapa_id,
                piloto_id=vinculo.piloto_id,
                autonomo_anterior_id=id,
                vinculo_anterior_id=vinculo.id,
                cargo_id=vinculo.cargo_id,
                motivo=motivo_saida,
                observacao=observacao,
            )
        )
    db.commit()
    return redirect_with_message("/autonomos", success="Autonomo inativado e vinculos ativos encerrados.")


@router.get("/{id}/historico")
def historico(id: int, request: Request, db: Session = Depends(get_db)):
    autonomo = db.get(Autonomo, id)
    if not autonomo:
        return redirect_with_message("/autonomos", error="Autonomo nao encontrado.")
    movimentacoes = (
        db.query(Movimentacao)
        .filter(or_(Movimentacao.autonomo_anterior_id == id, Movimentacao.autonomo_novo_id == id))
        .order_by(Movimentacao.data_movimentacao.desc(), Movimentacao.id.desc())
        .all()
    )
    vinculos = db.query(Vinculo).filter(Vinculo.autonomo_id == id).order_by(Vinculo.data_inicio.desc()).all()
    return templates.TemplateResponse(
        "autonomos/historico.html",
        {"request": request, "autonomo": autonomo, "movimentacoes": movimentacoes, "vinculos": vinculos, **flash_from_request(request)},
    )
