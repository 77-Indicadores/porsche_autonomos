from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import DimEtapa, DimProva, FatoPilotoAutonomoProva
from app.template_config import templates
from app.utils import flash_from_request

router = APIRouter(tags=["equipes"])


@router.get("/equipes")
def equipes(request: Request, id_etapa: str = "", id_prova: str = "", db: Session = Depends(get_db)):
    query = db.query(FatoPilotoAutonomoProva)

    if id_etapa:
        query = query.filter(FatoPilotoAutonomoProva.id_etapa == int(id_etapa))

    if id_prova:
        query = query.filter(FatoPilotoAutonomoProva.id_prova == int(id_prova))

    fatos = query.order_by(
        FatoPilotoAutonomoProva.id_etapa,
        FatoPilotoAutonomoProva.id_prova,
        FatoPilotoAutonomoProva.id_piloto,
        FatoPilotoAutonomoProva.id_carro,
        FatoPilotoAutonomoProva.funcao_autonomo,
    ).all()

    grupos = {}

    for f in fatos:
        chave = (f.id_etapa, f.id_prova, f.id_piloto, f.id_carro)

        if chave not in grupos:
            grupos[chave] = {
                "etapa": f.etapa,
                "categoria": f.prova,
                "piloto": f.piloto,
                "carro": f.carro,
                "ativos": [],
                "substituidos": [],
                "valor_total": 0,
                "dias_total": 0,
            }

        if f.status_vinculo == "Ativo":
            grupos[chave]["ativos"].append(f)
            grupos[chave]["valor_total"] += float(f.valor_fechado_etapa or 0)
            grupos[chave]["dias_total"] += int(f.dias_trabalhados or 0)

        elif f.status_vinculo == "Substituido":
            grupos[chave]["substituidos"].append(f)

    return templates.TemplateResponse(
        "equipes/index.html",
        {
            "request": request,
            "equipes": list(grupos.values()),
            "etapas": db.query(DimEtapa).order_by(DimEtapa.temporada.desc(), DimEtapa.nome_etapa).all(),
            "categorias": db.query(DimProva).order_by(DimProva.data_prova.desc()).all(),
            "filtros": {"id_etapa": id_etapa, "id_prova": id_prova},
            **flash_from_request(request),
        },
    )
