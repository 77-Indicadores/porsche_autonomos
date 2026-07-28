
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.database import get_db
from app.models import (
    DimAutonomo,
    DimCarro,
    DimCargoAutonomo,
    DimEtapa,
    DimMotivoTroca,
    DimPiloto,
    DimProva,
)
from app.template_config import templates


router = APIRouter(tags=["referencias_importacao"])


@router.get("/ids-importacao")
def ids_importacao(request: Request, db: Session = Depends(get_db)):
    pilotos = db.query(DimPiloto).order_by(DimPiloto.nome_piloto).all()
    autonomos = db.query(DimAutonomo).order_by(DimAutonomo.nome_autonomo).all()
    etapas = db.query(DimEtapa).order_by(DimEtapa.nome_etapa).all()
    categorias = db.query(DimProva).order_by(DimProva.nome_prova).all()
    carros = db.query(DimCarro).order_by(DimCarro.chassi).all()
    cargos = db.query(DimCargoAutonomo).order_by(DimCargoAutonomo.nome_cargo).all()
    motivos = db.query(DimMotivoTroca).order_by(DimMotivoTroca.motivo_troca).all()

    try:
        equipes_gerais = db.execute(text("""
            SELECT
                eg.id_equipe_geral,
                eg.nome_equipe,
                eg.id_etapa,
                eg.id_prova,
                eg.qtd_pessoas,
                eg.custo_total,
                de.nome_etapa,
                dp.nome_prova
            FROM equipe_geral eg
            LEFT JOIN dim_etapas de ON de.id_etapa = eg.id_etapa
            LEFT JOIN dim_categorias dp ON dp.id_prova = eg.id_prova
            ORDER BY eg.nome_equipe
        """)).mappings().all()
    except Exception:
        equipes_gerais = []

    return templates.TemplateResponse(
        "referencias/ids_importacao.html",
        {
            "request": request,
            "pilotos": pilotos,
            "autonomos": autonomos,
            "etapas": etapas,
            "categorias": categorias,
            "carros": carros,
            "cargos": cargos,
            "motivos": motivos,
            "equipes_gerais": equipes_gerais,
        },
    )
