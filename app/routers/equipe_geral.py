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
from app.utils import flash_from_request, redirect_with_message

router = APIRouter(tags=["equipe_geral"])

metadata_equipe = MetaData()

equipe_geral = Table(
    "equipe_geral",
    metadata_equipe,
    Column("id_equipe_geral", Integer, primary_key=True, autoincrement=True),
    Column("id_etapa", Integer, nullable=True),
    Column("id_prova", Integer, nullable=True),
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
    Então garantimos compatibilidade com bases já publicadas.
    """
    try:
        with engine.begin() as conn:
            dialect = conn.dialect.name

            if dialect == "postgresql":
                conn.execute(text("""
                    ALTER TABLE IF EXISTS equipe_geral
                    ALTER COLUMN id_etapa DROP NOT NULL
                """))

                conn.execute(text("""
                    ALTER TABLE IF EXISTS equipe_geral
                    ALTER COLUMN id_prova DROP NOT NULL
                """))

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


@router.get("/equipe-geral")
def index(request: Request, db: Session = Depends(get_db)):
    rows = db.execute(
        select(equipe_geral).order_by(equipe_geral.c.id_equipe_geral.desc())
    ).mappings().all()

    etapas = db.query(DimEtapa).order_by(DimEtapa.temporada.desc(), DimEtapa.nome_etapa).all()
    provas = db.query(DimProva).order_by(DimProva.nome_prova).all()

    return templates.TemplateResponse(
        "equipe_geral/index.html",
        {
            "request": request,
            "equipes": [dict(e) for e in rows],
            "etapas": etapas,
            "provas": provas,
            **flash_from_request(request),
        },
    )


@router.post("/equipe-geral")
def salvar_equipe(
    id_equipe_geral: str = Form(""),
    nome_equipe: str = Form(...),
    id_etapa: str = Form(""),
    id_prova: str = Form(""),
    qtd_pessoas: str = Form("1"),
    custo_total: str = Form(""),
    observacoes: str = Form(""),
    db: Session = Depends(get_db),
):
    nome_equipe = str(nome_equipe or "").strip()
    if not nome_equipe:
        return redirect_with_message("/equipe-geral", error="Informe o nome da equipe.")

    def _parse_float(v: str):
        try:
            return float(str(v or "").strip().replace(",", ".")) if str(v or "").strip() else None
        except ValueError:
            return None

    def _parse_int(v: str):
        try:
            return int(str(v or "").strip()) if str(v or "").strip() else None
        except ValueError:
            return None

    dados = {
        "nome_equipe": nome_equipe,
        "id_etapa": _parse_int(id_etapa),
        "id_prova": _parse_int(id_prova),
        "qtd_pessoas": _parse_float(qtd_pessoas) or 1,
        "custo_total": _parse_float(custo_total),
        "observacoes": str(observacoes or "").strip(),
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
