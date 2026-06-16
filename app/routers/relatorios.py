from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import DimAutonomo, DimEtapa, DimMotivoTroca, DimPiloto, DimProva, FatoPilotoAutonomoProva
from app.template_config import templates
from app.utils import flash_from_request, parse_date

router = APIRouter(prefix="/relatorios", tags=["relatorios"])


def opts(db: Session):
    return {
        "pilotos": db.query(DimPiloto).order_by(DimPiloto.nome_piloto).all(),
        "autonomos": db.query(DimAutonomo).order_by(DimAutonomo.nome_autonomo).all(),
        "etapas": db.query(DimEtapa).order_by(DimEtapa.nome_etapa).all(),
        "provas": db.query(DimProva).order_by(DimProva.nome_prova).all(),
        "motivos": db.query(DimMotivoTroca).order_by(DimMotivoTroca.motivo_troca).all(),
    }


def base_query(db, id_piloto="", id_autonomo="", id_etapa="", id_prova="", status=""):
    q = db.query(FatoPilotoAutonomoProva)
    if id_piloto:
        q = q.filter(FatoPilotoAutonomoProva.id_piloto == int(id_piloto))
    if id_autonomo:
        q = q.filter(FatoPilotoAutonomoProva.id_autonomo == int(id_autonomo))
    if id_etapa:
        q = q.filter(FatoPilotoAutonomoProva.id_etapa == int(id_etapa))
    if id_prova:
        q = q.filter(FatoPilotoAutonomoProva.id_prova == int(id_prova))
    if status:
        q = q.filter(FatoPilotoAutonomoProva.status_vinculo == status)
    return q


@router.get("/historico-piloto")
def historico_piloto(request: Request, id_piloto: str = "", id_etapa: str = "", id_prova: str = "", status: str = "", db: Session = Depends(get_db)):
    fatos = base_query(db, id_piloto=id_piloto, id_etapa=id_etapa, id_prova=id_prova, status=status).order_by(FatoPilotoAutonomoProva.id_fato.desc()).all()
    return templates.TemplateResponse("relatorios/historico_piloto.html", {"request": request, "fatos": fatos, "filtros": locals(), **opts(db), **flash_from_request(request)})


@router.get("/historico-autonomo")
def historico_autonomo(request: Request, id_autonomo: str = "", tipo: str = "", status: str = "", db: Session = Depends(get_db)):
    q = base_query(db, id_autonomo=id_autonomo, status=status).join(DimAutonomo, FatoPilotoAutonomoProva.id_autonomo == DimAutonomo.id_autonomo)
    if tipo:
        q = q.filter(DimAutonomo.tipo_autonomo == tipo)
    return templates.TemplateResponse("relatorios/historico_autonomo.html", {"request": request, "fatos": q.order_by(FatoPilotoAutonomoProva.id_fato.desc()).all(), "filtros": locals(), **opts(db), **flash_from_request(request)})


@router.get("/custos")
def custos(request: Request, id_etapa: str = "", id_prova: str = "", id_piloto: str = "", tipo: str = "", db: Session = Depends(get_db)):
    q = base_query(db, id_piloto=id_piloto, id_etapa=id_etapa, id_prova=id_prova).join(DimAutonomo, FatoPilotoAutonomoProva.id_autonomo == DimAutonomo.id_autonomo)
    if tipo:
        q = q.filter(DimAutonomo.tipo_autonomo == tipo)
    return templates.TemplateResponse("relatorios/custos.html", {"request": request, "fatos": q.order_by(FatoPilotoAutonomoProva.id_fato.desc()).all(), "filtros": locals(), **opts(db), **flash_from_request(request)})


@router.get("/trocas")
def trocas(request: Request, data_inicial: str = "", data_final: str = "", id_piloto: str = "", id_motivo_troca: str = "", db: Session = Depends(get_db)):
    q = db.query(FatoPilotoAutonomoProva).filter(FatoPilotoAutonomoProva.data_troca.is_not(None))
    if data_inicial:
        q = q.filter(FatoPilotoAutonomoProva.data_troca >= parse_date(data_inicial))
    if data_final:
        q = q.filter(FatoPilotoAutonomoProva.data_troca <= parse_date(data_final))
    if id_piloto:
        q = q.filter(FatoPilotoAutonomoProva.id_piloto == int(id_piloto))
    if id_motivo_troca:
        q = q.filter(FatoPilotoAutonomoProva.id_motivo_troca == int(id_motivo_troca))
    return templates.TemplateResponse("relatorios/trocas.html", {"request": request, "fatos": q.order_by(FatoPilotoAutonomoProva.data_troca.desc()).all(), "filtros": locals(), **opts(db), **flash_from_request(request)})


@router.get("/avaliacoes")
def avaliacoes(request: Request, id_piloto: str = "", id_autonomo: str = "", id_etapa: str = "", id_prova: str = "", nota: str = "", db: Session = Depends(get_db)):
    q = base_query(db, id_piloto=id_piloto, id_autonomo=id_autonomo, id_etapa=id_etapa, id_prova=id_prova).filter(FatoPilotoAutonomoProva.nota_geral.is_not(None))
    if nota:
        q = q.filter(FatoPilotoAutonomoProva.nota_geral >= float(nota))
    return templates.TemplateResponse("relatorios/avaliacoes.html", {"request": request, "fatos": q.order_by(FatoPilotoAutonomoProva.nota_geral.desc()).all(), "filtros": locals(), **opts(db), **flash_from_request(request)})
