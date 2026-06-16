from datetime import date

from fastapi import APIRouter, Depends, Request
from sqlalchemy import extract, func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import DimAutonomo, DimPiloto, FatoPilotoAutonomoProva
from app.template_config import templates
from app.utils import flash_from_request

router = APIRouter(tags=["dashboard"])


@router.get("/")
def dashboard(request: Request, db: Session = Depends(get_db)):
    hoje = date.today()
    fatos = db.query(FatoPilotoAutonomoProva).all()
    custo_total = sum(float(f.valor_fechado_etapa or 0) for f in fatos)
    custo_pago = sum(float(f.valor_fechado_etapa or 0) for f in fatos if f.status_pagamento == "Pago")
    custo_pendente = sum(float(f.valor_fechado_etapa or 0) for f in fatos if f.status_pagamento == "Pendente")
    notas = [float(f.nota_geral) for f in fatos if f.nota_geral is not None]
    media = sum(notas) / len(notas) if notas else 0

    cards = {
        "pilotos": db.query(func.count(DimPiloto.id_piloto)).filter(DimPiloto.status_piloto == "Ativo").scalar() or 0,
        "autonomos": db.query(func.count(DimAutonomo.id_autonomo)).filter(DimAutonomo.status_autonomo == "Ativo").scalar() or 0,
        "vinculos": db.query(func.count(FatoPilotoAutonomoProva.id_fato)).filter(FatoPilotoAutonomoProva.status_vinculo == "Ativo").scalar() or 0,
        "trocas_mes": db.query(func.count(FatoPilotoAutonomoProva.id_fato)).filter(
            FatoPilotoAutonomoProva.data_troca.is_not(None),
            extract("month", FatoPilotoAutonomoProva.data_troca) == hoje.month,
            extract("year", FatoPilotoAutonomoProva.data_troca) == hoje.year,
        ).scalar() or 0,
        "custo_total": custo_total,
        "custo_pendente": custo_pendente,
        "custo_pago": custo_pago,
        "media": media,
    }

    def group_sum(label_getter):
        data = {}
        for fato in fatos:
            label = label_getter(fato) or "-"
            data[label] = data.get(label, 0) + float(fato.valor_fechado_etapa or 0)
        return sorted(data.items(), key=lambda x: x[1], reverse=True)[:8]

    charts = {
        "etapa": group_sum(lambda f: f.etapa.nome_etapa),
        "piloto": group_sum(lambda f: f.piloto.nome_piloto),
        "tipo": group_sum(lambda f: f.autonomo.tipo_autonomo),
        "autonomo": group_sum(lambda f: f.autonomo.nome_autonomo),
    }

    motivo = {}
    for fato in fatos:
        if fato.motivo_troca:
            motivo[fato.motivo_troca.motivo_troca] = motivo.get(fato.motivo_troca.motivo_troca, 0) + 1
    charts["motivos"] = sorted(motivo.items(), key=lambda x: x[1], reverse=True)

    aval = {}
    for fato in fatos:
        if fato.nota_geral is not None:
            aval.setdefault(fato.autonomo.nome_autonomo, []).append(float(fato.nota_geral))
    charts["avaliacoes"] = [(nome, sum(vals) / len(vals)) for nome, vals in aval.items()]

    resumo = db.query(FatoPilotoAutonomoProva).filter(FatoPilotoAutonomoProva.status_vinculo == "Ativo").order_by(FatoPilotoAutonomoProva.id_fato.desc()).limit(20).all()
    return templates.TemplateResponse("dashboard.html", {"request": request, "cards": cards, "charts": charts, "resumo": resumo, **flash_from_request(request)})
