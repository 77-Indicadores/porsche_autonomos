from datetime import date

from fastapi import APIRouter, Depends, Request
from sqlalchemy import extract, func, text
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import DimAutonomo, DimPiloto, FatoPilotoAutonomoProva
from app.template_config import templates
from app.utils import flash_from_request

router = APIRouter(tags=["dashboard"])


def fmt_money(value):
    try:
        return f"R$ {float(value or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "R$ 0,00"


def fmt_qtd(value):
    try:
        v = float(value or 0)
        if v.is_integer():
            return str(int(v))
        return str(v).replace(".", ",")
    except Exception:
        return str(value or 0)


def table_exists(db: Session, table_name: str) -> bool:
    try:
        dialect = db.bind.dialect.name

        if dialect == "sqlite":
            row = db.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name=:table_name"),
                {"table_name": table_name},
            ).first()
            return row is not None

        if dialect == "postgresql":
            row = db.execute(
                text("""
                    SELECT to_regclass(:table_name) IS NOT NULL
                """),
                {"table_name": table_name},
            ).scalar()
            return bool(row)

        return True

    except Exception:
        return False


def carregar_indicadores_equipe_geral(db: Session):
    base = {
        "qtd_equipes": 0,
        "qtd_pessoas": 0.0,
        "custo_total": 0.0,
        "custo_medio_pessoa": 0.0,
        "top_equipes": [],
        "por_categoria": [],
        "por_etapa": [],
        "custo_total_fmt": fmt_money(0),
        "custo_medio_pessoa_fmt": fmt_money(0),
        "qtd_pessoas_fmt": fmt_qtd(0),
    }

    if not table_exists(db, "equipe_geral"):
        return base

    try:
        row = db.execute(text("""
            SELECT
                COUNT(*) AS qtd_equipes,
                COALESCE(SUM(qtd_pessoas), 0) AS qtd_pessoas,
                COALESCE(SUM(custo_total), 0) AS custo_total
            FROM equipe_geral
        """)).mappings().first()

        base["qtd_equipes"] = int(row["qtd_equipes"] or 0)
        base["qtd_pessoas"] = float(row["qtd_pessoas"] or 0)
        base["custo_total"] = float(row["custo_total"] or 0)
        base["custo_medio_pessoa"] = (
            base["custo_total"] / base["qtd_pessoas"]
            if base["qtd_pessoas"] else 0
        )

        base["custo_total_fmt"] = fmt_money(base["custo_total"])
        base["custo_medio_pessoa_fmt"] = fmt_money(base["custo_medio_pessoa"])
        base["qtd_pessoas_fmt"] = fmt_qtd(base["qtd_pessoas"])

        base["top_equipes"] = [
            dict(r) for r in db.execute(text("""
                SELECT
                    eg.id_equipe_geral,
                    eg.nome_equipe,
                    eg.qtd_pessoas,
                    eg.custo_total,
                    de.nome_etapa,
                    dp.nome_prova
                FROM equipe_geral eg
                LEFT JOIN dim_etapas de ON de.id_etapa = eg.id_etapa
                LEFT JOIN dim_categorias dp ON dp.id_prova = eg.id_prova
                ORDER BY COALESCE(eg.custo_total, 0) DESC
                LIMIT 5
            """)).mappings().all()
        ]

        base["por_categoria"] = [
            dict(r) for r in db.execute(text("""
                SELECT
                    COALESCE(dp.nome_prova, 'Sem categoria') AS nome,
                    COUNT(*) AS qtd_equipes,
                    COALESCE(SUM(eg.qtd_pessoas), 0) AS qtd_pessoas,
                    COALESCE(SUM(eg.custo_total), 0) AS custo_total
                FROM equipe_geral eg
                LEFT JOIN dim_categorias dp ON dp.id_prova = eg.id_prova
                GROUP BY COALESCE(dp.nome_prova, 'Sem categoria')
                ORDER BY COALESCE(SUM(eg.custo_total), 0) DESC
                LIMIT 6
            """)).mappings().all()
        ]

        base["por_etapa"] = [
            dict(r) for r in db.execute(text("""
                SELECT
                    COALESCE(de.nome_etapa, 'Sem etapa') AS nome,
                    COUNT(*) AS qtd_equipes,
                    COALESCE(SUM(eg.qtd_pessoas), 0) AS qtd_pessoas,
                    COALESCE(SUM(eg.custo_total), 0) AS custo_total
                FROM equipe_geral eg
                LEFT JOIN dim_etapas de ON de.id_etapa = eg.id_etapa
                GROUP BY COALESCE(de.nome_etapa, 'Sem etapa')
                ORDER BY COALESCE(SUM(eg.custo_total), 0) DESC
                LIMIT 6
            """)).mappings().all()
        ]

    except Exception as exc:
        print(f"AVISO - erro ao carregar indicadores de equipe geral: {exc}")

    return base


def carregar_indicadores_composicao(db: Session):
    base = {
        "qtd_regras": 0,
        "qtd_esperada": 0.0,
        "qtd_esperada_fmt": fmt_qtd(0),
    }

    if not table_exists(db, "composicao_padrao_equipe"):
        return base

    try:
        row = db.execute(text("""
            SELECT
                COUNT(*) AS qtd_regras,
                COALESCE(SUM(qtd_esperada), 0) AS qtd_esperada
            FROM composicao_padrao_equipe
        """)).mappings().first()

        base["qtd_regras"] = int(row["qtd_regras"] or 0)
        base["qtd_esperada"] = float(row["qtd_esperada"] or 0)
        base["qtd_esperada_fmt"] = fmt_qtd(base["qtd_esperada"])

    except Exception as exc:
        print(f"AVISO - erro ao carregar composição padrão no dashboard: {exc}")

    return base


@router.get("/")
def dashboard(request: Request, db: Session = Depends(get_db)):
    hoje = date.today()

    fatos = db.query(FatoPilotoAutonomoProva).all()

    custo_autonomos = sum(float(f.valor_fechado_etapa or 0) for f in fatos)
    custo_pago = sum(float(f.valor_fechado_etapa or 0) for f in fatos if f.status_pagamento == "Pago")
    custo_pendente = sum(float(f.valor_fechado_etapa or 0) for f in fatos if f.status_pagamento == "Pendente")

    notas = [float(f.nota_geral) for f in fatos if f.nota_geral is not None]
    media = sum(notas) / len(notas) if notas else 0

    equipe_geral = carregar_indicadores_equipe_geral(db)
    composicao = carregar_indicadores_composicao(db)

    custo_total_geral = custo_autonomos + float(equipe_geral.get("custo_total") or 0)

    qtd_carros_alocados = len({
        f.id_carro
        for f in fatos
        if f.id_carro is not None and (f.status_vinculo or "").lower() == "ativo"
    })

    cards = {
        "pilotos": db.query(func.count(DimPiloto.id_piloto)).filter(DimPiloto.status_piloto == "Ativo").scalar() or 0,
        "autonomos": db.query(func.count(DimAutonomo.id_autonomo)).filter(DimAutonomo.status_autonomo == "Ativo").scalar() or 0,
        "vinculos": db.query(func.count(FatoPilotoAutonomoProva.id_fato)).filter(FatoPilotoAutonomoProva.status_vinculo == "Ativo").scalar() or 0,
        "trocas_mes": db.query(func.count(FatoPilotoAutonomoProva.id_fato)).filter(
            FatoPilotoAutonomoProva.data_troca.is_not(None),
            extract("month", FatoPilotoAutonomoProva.data_troca) == hoje.month,
            extract("year", FatoPilotoAutonomoProva.data_troca) == hoje.year,
        ).scalar() or 0,
        "carros_alocados": qtd_carros_alocados,
        "custo_autonomos": custo_autonomos,
        "custo_equipe_geral": equipe_geral.get("custo_total", 0),
        "custo_total": custo_total_geral,
        "custo_pendente": custo_pendente,
        "custo_pago": custo_pago,
        "media": media,
    }

    def group_sum(label_getter):
        data = {}
        for fato in fatos:
            try:
                label = label_getter(fato) or "-"
            except Exception:
                label = "-"
            data[label] = data.get(label, 0) + float(fato.valor_fechado_etapa or 0)
        return sorted(data.items(), key=lambda x: x[1], reverse=True)[:8]

    charts = {
        "etapa": group_sum(lambda f: f.etapa.nome_etapa if f.etapa else "-"),
        "piloto": group_sum(lambda f: f.piloto.nome_piloto if f.piloto else "-"),
        "tipo": group_sum(lambda f: f.autonomo.tipo_autonomo if f.autonomo else "-"),
        "autonomo": group_sum(lambda f: f.autonomo.nome_autonomo if f.autonomo else "-"),
    }

    motivo = {}
    for fato in fatos:
        if fato.motivo_troca:
            motivo[fato.motivo_troca.motivo_troca] = motivo.get(fato.motivo_troca.motivo_troca, 0) + 1
    charts["motivos"] = sorted(motivo.items(), key=lambda x: x[1], reverse=True)

    aval = {}
    for fato in fatos:
        if fato.nota_geral is not None and fato.autonomo:
            aval.setdefault(fato.autonomo.nome_autonomo, []).append(float(fato.nota_geral))
    charts["avaliacoes"] = [(nome, sum(vals) / len(vals)) for nome, vals in aval.items()]

    resumo = (
        db.query(FatoPilotoAutonomoProva)
        .filter(FatoPilotoAutonomoProva.status_vinculo == "Ativo")
        .order_by(FatoPilotoAutonomoProva.id_fato.desc())
        .limit(20)
        .all()
    )

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "cards": cards,
            "charts": charts,
            "resumo": resumo,
            "equipe_geral": equipe_geral,
            "composicao": composicao,
            **flash_from_request(request),
        },
    )
