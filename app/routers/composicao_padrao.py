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
    func,
)
from sqlalchemy.orm import Session

from app.database import engine, get_db
from app.models import DimCarro, DimCargoAutonomo, DimEtapa, DimProva, FatoPilotoAutonomoProva
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

    except Exception as exc:
        print(f"AVISO - não consegui ajustar schema composicao_padrao_equipe: {exc}")


garantir_schema()


def options(db: Session):
    return {
        "etapas": db.query(DimEtapa).order_by(DimEtapa.temporada.desc(), DimEtapa.data_inicio.desc()).all(),
        "provas": db.query(DimProva).order_by(DimProva.data_prova.desc()).all(),
        "carros": db.query(DimCarro).order_by(DimCarro.numero_carro).all(),
        "cargos": db.query(DimCargoAutonomo).order_by(DimCargoAutonomo.nome_cargo).all(),
    }


def to_int_or_none(value):
    value = str(value or "").strip()
    if not value:
        return None
    return int(value)


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


def get_nome_carro(db: Session, id_carro):
    if not id_carro:
        return "Todos"
    obj = db.get(DimCarro, id_carro)
    if not obj:
        return f"ID {id_carro}"
    numero = getattr(obj, "numero_carro", "") or ""
    modelo = getattr(obj, "modelo", "") or ""
    return f"{numero} - {modelo}".strip(" -")


def get_nome_cargo(db: Session, id_cargo):
    obj = db.get(DimCargoAutonomo, id_cargo)
    return obj.nome_cargo if obj else f"ID {id_cargo}"


def normalizar(texto):
    return " ".join(str(texto or "").strip().lower().split())


def buscar_cargo_por_funcao(db: Session, funcao_autonomo):
    nome = normalizar(funcao_autonomo)
    if not nome:
        return None

    cargos = db.query(DimCargoAutonomo).all()
    for cargo in cargos:
        if normalizar(cargo.nome_cargo) == nome:
            return cargo

    return None


def gerar_itens_pelas_alocacoes(
    db: Session,
    id_etapa: str = "",
    id_prova: str = "",
    id_carro: str = "",
    id_cargo_autonomo: str = "",
    status: str = "",
):
    if status and status != "Ativo":
        return []

    query = db.query(
        FatoPilotoAutonomoProva.id_etapa,
        FatoPilotoAutonomoProva.id_prova,
        FatoPilotoAutonomoProva.id_carro,
        FatoPilotoAutonomoProva.funcao_autonomo,
        func.count(FatoPilotoAutonomoProva.id_fato).label("qtd_esperada"),
        func.avg(FatoPilotoAutonomoProva.valor_fechado_etapa).label("custo_medio_esperado"),
    )

    if id_etapa:
        query = query.filter(FatoPilotoAutonomoProva.id_etapa == int(id_etapa))

    if id_prova:
        query = query.filter(FatoPilotoAutonomoProva.id_prova == int(id_prova))

    if id_carro:
        query = query.filter(FatoPilotoAutonomoProva.id_carro == int(id_carro))

    query = query.group_by(
        FatoPilotoAutonomoProva.id_etapa,
        FatoPilotoAutonomoProva.id_prova,
        FatoPilotoAutonomoProva.id_carro,
        FatoPilotoAutonomoProva.funcao_autonomo,
    )

    rows = query.all()
    items = []

    for row in rows:
        cargo = buscar_cargo_por_funcao(db, row.funcao_autonomo)

        if id_cargo_autonomo:
            if not cargo or cargo.id_cargo_autonomo != int(id_cargo_autonomo):
                continue

        qtd = float(row.qtd_esperada or 0)
        custo = float(row.custo_medio_esperado or 0)

        items.append({
            "id_composicao": None,
            "id_etapa": row.id_etapa,
            "id_prova": row.id_prova,
            "id_carro": row.id_carro,
            "id_cargo_autonomo": cargo.id_cargo_autonomo if cargo else "",
            "qtd_esperada": int(qtd) if qtd.is_integer() else qtd,
            "custo_medio_esperado": custo,
            "custo_total_esperado": qtd * custo,
            "status": "Ativo",
            "observacoes": "Gerado automaticamente pelas equipes alocadas.",
            "nome_etapa": get_nome_etapa(db, row.id_etapa),
            "nome_prova": get_nome_prova(db, row.id_prova),
            "nome_carro": get_nome_carro(db, row.id_carro),
            "nome_cargo": cargo.nome_cargo if cargo else (row.funcao_autonomo or "-"),
            "origem": "alocacoes",
        })

    return items


@router.get("/composicao-padrao")
def index(
    request: Request,
    id_etapa: str = "",
    id_prova: str = "",
    id_carro: str = "",
    id_cargo_autonomo: str = "",
    status: str = "",
    db: Session = Depends(get_db),
):
    query = select(composicao_padrao_equipe)

    filtros = []

    filtros.append(composicao_padrao_equipe.c.id_cargo_autonomo.isnot(None))

    if id_etapa:
        filtros.append(composicao_padrao_equipe.c.id_etapa == int(id_etapa))

    if id_prova:
        filtros.append(composicao_padrao_equipe.c.id_prova == int(id_prova))

    if id_carro:
        filtros.append(composicao_padrao_equipe.c.id_carro == int(id_carro))

    if id_cargo_autonomo:
        filtros.append(composicao_padrao_equipe.c.id_cargo_autonomo == int(id_cargo_autonomo))

    if status:
        filtros.append(composicao_padrao_equipe.c.status == status)

    if filtros:
        query = query.where(and_(*filtros))

    rows = db.execute(
        query.order_by(
            composicao_padrao_equipe.c.status,
            composicao_padrao_equipe.c.id_etapa,
            composicao_padrao_equipe.c.id_prova,
            composicao_padrao_equipe.c.id_carro,
            composicao_padrao_equipe.c.id_cargo_autonomo,
        )
    ).mappings().all()

    items = []

    total_qtd = 0
    total_custo = 0

    for r in rows:
        item = dict(r)
        item["nome_etapa"] = get_nome_etapa(db, item.get("id_etapa"))
        item["nome_prova"] = get_nome_prova(db, item.get("id_prova"))
        item["nome_carro"] = get_nome_carro(db, item.get("id_carro"))
        item["nome_cargo"] = get_nome_cargo(db, item.get("id_cargo_autonomo"))

        qtd = item.get("qtd_esperada") or 0
        custo = item.get("custo_medio_esperado") or 0
        item["custo_total_esperado"] = float(qtd) * float(custo)

        total_qtd += qtd
        total_custo += item["custo_total_esperado"]

        items.append(item)

    if not items:
        items = gerar_itens_pelas_alocacoes(
            db,
            id_etapa=id_etapa,
            id_prova=id_prova,
            id_carro=id_carro,
            id_cargo_autonomo=id_cargo_autonomo,
            status=status,
        )
        total_qtd = sum(float(item.get("qtd_esperada") or 0) for item in items)
        total_custo = sum(float(item.get("custo_total_esperado") or 0) for item in items)

    return templates.TemplateResponse(
        "composicao_padrao/index.html",
        {
            "request": request,
            "items": items,
            "total_qtd": total_qtd,
            "total_custo": total_custo,
            "filtros": {
                "id_etapa": id_etapa,
                "id_prova": id_prova,
                "id_carro": id_carro,
                "id_cargo_autonomo": id_cargo_autonomo,
                "status": status,
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
    id_carro: str = Form(""),
    id_cargo_autonomo: int = Form(...),
    qtd_esperada: int = Form(...),
    custo_medio_esperado: str = Form(""),
    status: str = Form("Ativo"),
    observacoes: str = Form(""),
    db: Session = Depends(get_db),
):
    if qtd_esperada <= 0:
        return redirect_with_message("/composicao-padrao", error="Quantidade esperada deve ser maior que zero.")

    custo = parse_money(custo_medio_esperado)

    dados = {
        "id_etapa": to_int_or_none(id_etapa),
        "id_prova": to_int_or_none(id_prova),
        "id_carro": to_int_or_none(id_carro),
        "id_cargo_autonomo": id_cargo_autonomo,
        "qtd_esperada": qtd_esperada,
        "custo_medio_esperado": custo,
        "status": status,
        "observacoes": observacoes,
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
        msg = "Composição padrão atualizada com sucesso."

    else:
        dados["criado_em"] = datetime.utcnow()
        db.execute(insert(composicao_padrao_equipe).values(**dados))
        msg = "Composição padrão cadastrada com sucesso."

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
