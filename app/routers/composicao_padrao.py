from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    and_,
    delete,
    insert,
    select,
    text,
    update,
)
from sqlalchemy.orm import Session

from app.database import engine, get_db
from app.models import DimEtapa, DimProva
from app.template_config import templates
from app.utils import flash_from_request, parse_money, redirect_with_message

router = APIRouter(tags=["composicao_padrao"])

metadata_composicao = MetaData()

composicao_padrao_equipe = Table(
    "composicao_padrao_equipe",
    metadata_composicao,
    Column("id_composicao", Integer, primary_key=True, autoincrement=True),
    Column("id_etapa", Integer, nullable=True),
    Column("id_prova", Integer, nullable=True),
    Column("id_carro", Integer, nullable=True),
    Column("id_cargo_autonomo", Integer, nullable=True),
    Column("qtd_esperada", Float, nullable=False, default=1),
    Column("custo_medio_esperado", Float, nullable=True),
    Column("status", String(30), nullable=True, default="Ativo"),
    Column("observacoes", Text),
    Column("criado_em", DateTime, default=datetime.utcnow),
    Column("atualizado_em", DateTime, default=datetime.utcnow),
)

metadata_composicao.create_all(engine)


def garantir_schema():
    try:
        with engine.begin() as conn:
            dialect = conn.dialect.name

            if dialect == "postgresql":
                conn.execute(text("""
                    ALTER TABLE IF EXISTS composicao_padrao_equipe
                    ALTER COLUMN id_cargo_autonomo DROP NOT NULL
                """))

                conn.execute(text("""
                    ALTER TABLE IF EXISTS composicao_padrao_equipe
                    ALTER COLUMN qtd_esperada TYPE DOUBLE PRECISION
                    USING qtd_esperada::DOUBLE PRECISION
                """))

                conn.execute(text("""
                    ALTER TABLE IF EXISTS composicao_padrao_equipe
                    ADD COLUMN IF NOT EXISTS custo_medio_esperado DOUBLE PRECISION
                """))

            elif dialect == "sqlite":
                cols = [row[1] for row in conn.execute(text("PRAGMA table_info(composicao_padrao_equipe)")).fetchall()]
                if "custo_medio_esperado" not in cols:
                    conn.execute(text("ALTER TABLE composicao_padrao_equipe ADD COLUMN custo_medio_esperado REAL"))

    except Exception as exc:
        print(f"AVISO - não consegui ajustar schema composicao_padrao_equipe: {exc}")


garantir_schema()


QTD_OPTIONS = [
    1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5
]


def options(db: Session):
    return {
        "etapas": db.query(DimEtapa).order_by(DimEtapa.temporada.desc(), DimEtapa.data_inicio.desc()).all(),
        "provas": db.query(DimProva).order_by(DimProva.data_prova.desc()).all(),
        "qtd_options": QTD_OPTIONS,
    }


def to_int_or_none(value):
    value = str(value or "").strip()
    if not value:
        return None
    return int(value)


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
    if not id_etapa:
        return "Todas"
    obj = db.get(DimEtapa, id_etapa)
    return obj.nome_etapa if obj else f"ID {id_etapa}"


def get_nome_prova(db: Session, id_prova):
    if not id_prova:
        return "Todas"
    obj = db.get(DimProva, id_prova)
    return obj.nome_prova if obj else f"ID {id_prova}"


@router.get("/composicao-padrao")
def index(
    request: Request,
    id_etapa: str = "",
    id_prova: str = "",
    db: Session = Depends(get_db),
):
    query = select(composicao_padrao_equipe)

    filtros = []

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

    for r in rows:
        item = dict(r)
        item["nome_etapa"] = get_nome_etapa(db, item.get("id_etapa"))
        item["nome_prova"] = get_nome_prova(db, item.get("id_prova"))
        item["qtd_formatada"] = fmt_qtd(item.get("qtd_esperada"))
        item["valor_formatado"] = fmt_money(item.get("custo_medio_esperado"))

        total_qtd += float(item.get("qtd_esperada") or 0)
        total_valor += float(item.get("custo_medio_esperado") or 0)
        items.append(item)

    return templates.TemplateResponse(
        "composicao_padrao/index.html",
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


@router.post("/composicao-padrao")
def salvar(
    id_composicao: str = Form(""),
    id_etapa: str = Form(""),
    id_prova: str = Form(""),
    qtd_esperada: str = Form("1"),
    custo_medio_esperado: str = Form(""),
    db: Session = Depends(get_db),
):
    qtd = to_float_qtd(qtd_esperada)

    if qtd not in QTD_OPTIONS:
        return redirect_with_message("/composicao-padrao", error="Quantidade inválida.")

    if not id_etapa:
        return redirect_with_message("/composicao-padrao", error="Selecione uma etapa.")

    if not id_prova:
        return redirect_with_message("/composicao-padrao", error="Selecione uma categoria.")

    dados = {
        "id_etapa": to_int_or_none(id_etapa),
        "id_prova": to_int_or_none(id_prova),
        "id_carro": None,
        "id_cargo_autonomo": None,
        "qtd_esperada": qtd,
        "custo_medio_esperado": parse_money(custo_medio_esperado),
        "status": "Ativo",
        "observacoes": "",
        "atualizado_em": datetime.utcnow(),
    }

    id_composicao = str(id_composicao or "").strip()

    if id_composicao:
        existe = db.execute(
            select(composicao_padrao_equipe).where(
                composicao_padrao_equipe.c.id_composicao == int(id_composicao)
            )
        ).mappings().first()

        if not existe:
            return redirect_with_message("/composicao-padrao", error="Regra não encontrada.")

        db.execute(
            update(composicao_padrao_equipe)
            .where(composicao_padrao_equipe.c.id_composicao == int(id_composicao))
            .values(**dados)
        )

        msg = "Composição meta equipe atualizada com sucesso."

    else:
        dados["criado_em"] = datetime.utcnow()
        db.execute(insert(composicao_padrao_equipe).values(**dados))
        msg = "Composição meta equipe cadastrada com sucesso."

    db.commit()

    return redirect_with_message("/composicao-padrao", success=msg)


@router.post("/composicao-padrao/{id_composicao}/excluir")
def excluir(id_composicao: int, db: Session = Depends(get_db)):
    db.execute(
        delete(composicao_padrao_equipe).where(
            composicao_padrao_equipe.c.id_composicao == id_composicao
        )
    )
    db.commit()

    return redirect_with_message("/composicao-padrao", success="Regra excluída com sucesso.")
