from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import and_, delete, insert, select, update
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import DimEtapa, DimProva
from app.routers.composicao_padrao import composicao_padrao_equipe
from app.template_config import templates
from app.utils import flash_from_request, parse_money, redirect_with_message

router = APIRouter(tags=["composicao_meta_equipe"])

QTD_OPTIONS = [1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5]


def options(db: Session):
    return {
        "etapas": db.query(DimEtapa).order_by(DimEtapa.temporada.desc(), DimEtapa.data_inicio.desc()).all(),
        "provas": db.query(DimProva).order_by(DimProva.data_prova.desc()).all(),
        "qtd_options": QTD_OPTIONS,
    }


def to_float_qtd(value):
    value = str(value or "").strip().replace(",", ".")
    if not value:
        return 1.0
    return float(value)


def fmt_qtd(value):
    try:
        v = float(value or 0)
        if v.is_integer():
            return str(int(v))
        return str(v).replace(".", ",")
    except Exception:
        return value


def fmt_money(value):
    if value is None:
        return "-"
    return f"R$ {float(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def get_nome_etapa(db: Session, id_etapa):
    obj = db.get(DimEtapa, id_etapa)
    return obj.nome_etapa if obj else f"ID {id_etapa}"


def get_nome_prova(db: Session, id_prova):
    obj = db.get(DimProva, id_prova)
    return obj.nome_prova if obj else f"ID {id_prova}"


@router.get("/composicao-meta-equipe")
def index(
    request: Request,
    id_etapa: str = "",
    id_prova: str = "",
    db: Session = Depends(get_db),
):
    query = select(composicao_padrao_equipe)
    filtros = []

    filtros.append(composicao_padrao_equipe.c.id_cargo_autonomo.is_(None))

    if id_etapa:
        filtros.append(composicao_padrao_equipe.c.id_etapa == int(id_etapa))

    if id_prova:
        filtros.append(composicao_padrao_equipe.c.id_prova == int(id_prova))

    if filtros:
        query = query.where(and_(*filtros))

    rows = db.execute(
        query.order_by(
            composicao_padrao_equipe.c.id_etapa,
            composicao_padrao_equipe.c.id_prova,
        )
    ).mappings().all()

    items = []
    total_qtd = 0
    total_valor = 0

    for row in rows:
        item = dict(row)
        item["id_meta"] = item.get("id_composicao")
        item["nome_etapa"] = get_nome_etapa(db, item.get("id_etapa"))
        item["nome_prova"] = get_nome_prova(db, item.get("id_prova"))
        item["qtd_pessoas"] = item.get("qtd_esperada")
        item["valor"] = item.get("custo_medio_esperado")
        item["qtd_formatada"] = fmt_qtd(item.get("qtd_esperada"))
        item["valor_formatado"] = fmt_money(item.get("custo_medio_esperado"))

        total_qtd += float(item.get("qtd_esperada") or 0)
        total_valor += float(item.get("custo_medio_esperado") or 0)
        items.append(item)

    return templates.TemplateResponse(
        "composicao_meta_equipe/index.html",
        {
            "request": request,
            "items": items,
            "total_qtd": fmt_qtd(total_qtd),
            "total_valor": fmt_money(total_valor),
            "filtros": {
                "id_etapa": id_etapa,
                "id_prova": id_prova,
            },
            **options(db),
            **flash_from_request(request),
        },
    )


@router.post("/composicao-meta-equipe")
def salvar(
    id_meta: str = Form(""),
    id_etapa: str = Form(""),
    id_prova: str = Form(""),
    qtd_pessoas: str = Form("1"),
    valor: str = Form(""),
    db: Session = Depends(get_db),
):
    qtd = to_float_qtd(qtd_pessoas)

    if qtd not in QTD_OPTIONS:
        return redirect_with_message("/composicao-meta-equipe", error="Quantidade inválida.")

    if not id_etapa:
        return redirect_with_message("/composicao-meta-equipe", error="Selecione uma etapa.")

    if not id_prova:
        return redirect_with_message("/composicao-meta-equipe", error="Selecione uma categoria.")

    dados = {
        "id_etapa": int(id_etapa),
        "id_prova": int(id_prova),
        "id_carro": None,
        "id_cargo_autonomo": None,
        "qtd_esperada": qtd,
        "custo_medio_esperado": parse_money(valor),
        "status": "Ativo",
        "observacoes": "",
        "atualizado_em": datetime.utcnow(),
    }

    id_meta = str(id_meta or "").strip()

    if id_meta:
        db.execute(
            update(composicao_padrao_equipe)
            .where(composicao_padrao_equipe.c.id_composicao == int(id_meta))
            .values(**dados)
        )
        msg = "Composição meta equipe atualizada com sucesso."
    else:
        dados["criado_em"] = datetime.utcnow()
        db.execute(insert(composicao_padrao_equipe).values(**dados))
        msg = "Composição meta equipe cadastrada com sucesso."

    db.commit()
    return redirect_with_message("/composicao-meta-equipe", success=msg)


@router.post("/composicao-meta-equipe/{id_meta}/excluir")
def excluir(id_meta: int, db: Session = Depends(get_db)):
    db.execute(delete(composicao_padrao_equipe).where(composicao_padrao_equipe.c.id_composicao == id_meta))
    db.commit()
    return redirect_with_message("/composicao-meta-equipe", success="Regra excluída com sucesso.")
