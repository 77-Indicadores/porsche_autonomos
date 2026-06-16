
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    DimAutonomo,
    DimEtapa,
    DimMotivoTroca,
    DimPiloto,
    DimProva,
    DimStatusPagamento,
    DimTipoProva,
    FatoPilotoAutonomoProva,
)
from app.template_config import templates
from app.utils import flash_from_request

router = APIRouter(tags=["setup"])


@router.get("/setup")
def setup_home(request: Request, db: Session = Depends(get_db)):
    cards = [
        {"titulo": "Pilotos", "qtd": db.query(DimPiloto).count(), "url": "/pilotos", "excel": "/excel/modelo/pilotos"},
        {"titulo": "Autônomos", "qtd": db.query(DimAutonomo).count(), "url": "/autonomos", "excel": "/excel/modelo/autonomos"},
        {"titulo": "Etapas", "qtd": db.query(DimEtapa).count(), "url": "/etapas", "excel": "/excel/modelo/etapas"},
        {"titulo": "Tipos de Prova", "qtd": db.query(DimTipoProva).count(), "url": "/tipos-prova", "excel": "/excel/modelo/tipos-prova"},
        {"titulo": "Provas", "qtd": db.query(DimProva).count(), "url": "/provas", "excel": "/excel/modelo/provas"},
        {"titulo": "Motivos de Troca", "qtd": db.query(DimMotivoTroca).count(), "url": "/motivos-troca", "excel": "/excel/modelo/motivos-troca"},
        {"titulo": "Status Pagamento", "qtd": db.query(DimStatusPagamento).count(), "url": "/excel/", "excel": "/excel/modelo/status-pagamento"},
        {"titulo": "Alocações", "qtd": db.query(FatoPilotoAutonomoProva).count(), "url": "/alocacoes", "excel": "/excel/modelo/alocacoes"},
    ]

    return templates.TemplateResponse(
        "setup/index.html",
        {
            "request": request,
            "cards": cards,
            **flash_from_request(request),
        },
    )
