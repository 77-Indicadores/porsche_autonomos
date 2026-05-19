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

router = APIRouter(tags=["equipe_geral"])

metadata_equipe = MetaData()

equipe_geral = Table(
    "equipe_geral",
    metadata_equipe,
    Column("id_equipe_geral", Integer, primary_key=True, autoincrement=True),
    Column("id_etapa", Integer, nullable=False),
    Column("id_prova", Integer, nullable=False),
    Column("nome_equipe", String(160), nullable=False),
    Column("qtd_pessoas", Float, nullable=False, default=1),
    Column("custo_total", Float, nullable=True),
    Column("observacoes", Text),
    Column("criado_em", DateTime, default=datetime.utcnow),
    Column("atualizado_em", DateTime, default=datetime.utcnow),
)

metadata_equipe.create_all(engine)


def garantir_schema():
    """
    create_all não altera tabela existente.
    Então garantimos a coluna qtd_pessoas em bases já publicadas.
    """
    try:
        with engine.begin() as conn:
            dialect = conn.dialect.name

            if dialect == "postgresql":
                conn.execute(text("""
                    ALTER TABLE IF EXISTS equipe_geral
                    ADD COLUMN IF NOT EXISTS qtd_pessoas DOUBLE PRECISION DEFAULT 1
                """))

                conn.execute(text("""
                    ALTER TABLE IF EXISTS equipe_geral
                    ALTER COLUMN observacoes TYPE TEXT
                """))

            elif dialect == "sqlite":
                cols = [row[1] for row in conn.execute(text("PRAGMA table_info(equipe_geral)")).fetchall()]
                if "qtd_pessoas" not in cols:
                    conn.execute(text("ALTER TABLE equipe_geral ADD COLUMN qtd_pessoas REAL DEFAULT 1"))

    except Exception as exc:
        print(f"AVISO - não consegui ajustar schema equipe_geral: {exc}")


garantir_schema()


QTD_OPTIONS = [1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5]


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


def to_float_qtd(value):
    value = str(value or "").strip().replace(",", ".")
    if not value:
        return 1.0
    return float(value)


def options(db: Session):
    return {
        "etapas": db.query(DimEtapa).order_by(DimEtapa.temporada.desc(), DimEtapa.data_inicio.desc()).all(),
        "provas": db.query(DimProva).order_by(DimProva.data_prova.desc()).all(),
        "qtd_options": QTD_OPTIONS,
    }


def nome_etapa(db: Session, id_etapa):
    obj = db.get(DimEtapa, id_etapa)
    return obj.nome_etapa if obj else f"ID {id_etapa}"


def nome_prova(db: Session, id_prova):
    obj = db.get(DimProva, id_prova)
    return obj.nome_prova if obj else f"ID {id_prova}"


@router.get("/equipe-geral")
def index(request: Request, db: Session = Depends(get_db)):
    rows = db.execute(
        select(equipe_geral).order_by(equipe_geral.c.id_equipe_geral.desc())
    ).mappings().all()

    equipes = []
    total_qtd = 0
    total_custo = 0

    for e in rows:
        d = dict(e)
        d["nome_etapa"] = nome_etapa(db, d["id_etapa"])
        d["nome_prova"] = nome_prova(db, d["id_prova"])
        d["qtd_pessoas_fmt"] = fmt_qtd(d.get("qtd_pessoas"))
        d["custo_total_fmt"] = fmt_money(d.get("custo_total"))

        total_qtd += float(d.get("qtd_pessoas") or 0)
        total_custo += float(d.get("custo_total") or 0)

        equipes.append(d)

    return templates.TemplateResponse(
        "equipe_geral/index.html",
        {
            "request": request,
            "equipes": equipes,
            "total_qtd": fmt_qtd(total_qtd),
            "total_custo": fmt_money(total_custo),
            **options(db),
            **flash_from_request(request),
        },
    )


@router.post("/equipe-geral")
def salvar_equipe(
    id_equipe_geral: str = Form(""),
    id_etapa: int = Form(...),
    id_prova: int = Form(...),
    nome_equipe: str = Form(...),
    qtd_pessoas: str = Form("1"),
    custo_total: str = Form(""),
    observacoes: str = Form(""),
    db: Session = Depends(get_db),
):
    qtd = to_float_qtd(qtd_pessoas)

    if qtd not in QTD_OPTIONS:
        return redirect_with_message("/equipe-geral", error="Quantidade de pessoas inválida.")

    dados = {
        "id_etapa": id_etapa,
        "id_prova": id_prova,
        "nome_equipe": nome_equipe,
        "qtd_pessoas": qtd,
        "custo_total": parse_money(custo_total),
        "observacoes": observacoes,
        "atualizado_em": datetime.utcnow(),
    }

    id_equipe_geral = str(id_equipe_geral or "").strip()

    if id_equipe_geral:
        db.execute(
            update(equipe_geral)
            .where(equipe_geral.c.id_equipe_geral == int(id_equipe_geral))
            .values(**dados)
        )
        msg = "Equipe geral atualizada com sucesso."
    else:
        dados["criado_em"] = datetime.utcnow()
        db.execute(insert(equipe_geral).values(**dados))
        msg = "Equipe geral cadastrada com sucesso."

    db.commit()

    return redirect_with_message("/equipe-geral", success=msg)


@router.post("/equipe-geral/{id_equipe_geral}/excluir")
def excluir_equipe(id_equipe_geral: int, db: Session = Depends(get_db)):
    db.execute(delete(equipe_geral).where(equipe_geral.c.id_equipe_geral == id_equipe_geral))
    db.commit()

    return redirect_with_message("/equipe-geral", success="Equipe geral excluída.")
