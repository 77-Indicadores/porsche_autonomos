from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import DimAutonomo, DimEtapa, DimMotivoTroca, DimPiloto, DimProva, DimTipoProva, FatoPilotoAutonomoProva
from app.template_config import templates
from app.utils import flash_from_request, parse_date, redirect_with_message

router = APIRouter(tags=["cadastros"])


def lists(db: Session):
    return {
        "pilotos": db.query(DimPiloto).order_by(DimPiloto.nome_piloto).all(),
        "autonomos": db.query(DimAutonomo).order_by(DimAutonomo.nome_autonomo).all(),
        "etapas": db.query(DimEtapa).order_by(DimEtapa.temporada.desc(), DimEtapa.nome_etapa).all(),
        "tipos": db.query(DimTipoProva).order_by(DimTipoProva.nome_tipo_prova).all(),
        "motivos": db.query(DimMotivoTroca).order_by(DimMotivoTroca.motivo_troca).all(),
    }


@router.get("/pilotos")
def pilotos(request: Request, q: str = "", db: Session = Depends(get_db)):
    query = db.query(DimPiloto)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(DimPiloto.nome_piloto.ilike(like), DimPiloto.equipe.ilike(like), DimPiloto.categoria_atual.ilike(like), DimPiloto.status_piloto.ilike(like)))
    return templates.TemplateResponse("cadastros/pilotos.html", {"request": request, "items": query.order_by(DimPiloto.nome_piloto).all(), "q": q, **flash_from_request(request)})


@router.post("/pilotos")
def salvar_piloto(
    id_piloto: str = Form(""),
    nome_piloto: str = Form(...),
    cpf: str = Form(""),
    telefone: str = Form(""),
    email: str = Form(""),
    equipe: str = Form(""),
    categoria_atual: str = Form(""),
    data_inclusao: str = Form(""),
    status_piloto: str = Form("Ativo"),
    observacoes: str = Form(""),
    db: Session = Depends(get_db),
):
    piloto = db.get(DimPiloto, int(id_piloto)) if id_piloto else DimPiloto()
    piloto.nome_piloto = nome_piloto
    piloto.cpf = cpf
    piloto.telefone = telefone
    piloto.email = email
    piloto.equipe = equipe
    piloto.categoria_atual = categoria_atual
    piloto.data_inclusao = parse_date(data_inclusao) or piloto.data_inclusao
    piloto.status_piloto = status_piloto
    piloto.observacoes = observacoes
    db.add(piloto)
    db.commit()
    return redirect_with_message("/pilotos", success="Piloto salvo com sucesso.")


@router.post("/pilotos/{id_piloto}/desligar")
def desligar_piloto(id_piloto: int, data_desligamento: str = Form(...), motivo: str = Form(...), db: Session = Depends(get_db)):
    piloto = db.get(DimPiloto, id_piloto)
    if not piloto:
        return redirect_with_message("/pilotos", error="Piloto nao encontrado.")
    piloto.status_piloto = "Desligado"
    piloto.data_desligamento = parse_date(data_desligamento)
    piloto.motivo_desligamento = motivo
    db.commit()
    return redirect_with_message("/pilotos", success="Piloto desligado sem exclusao fisica.")


@router.get("/autonomos")
def autonomos(request: Request, q: str = "", db: Session = Depends(get_db)):
    query = db.query(DimAutonomo)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(DimAutonomo.nome_autonomo.ilike(like), DimAutonomo.tipo_autonomo.ilike(like), DimAutonomo.especialidade.ilike(like), DimAutonomo.status_autonomo.ilike(like)))
    return templates.TemplateResponse("cadastros/autonomos.html", {"request": request, "items": query.order_by(DimAutonomo.nome_autonomo).all(), "q": q, **flash_from_request(request)})


@router.post("/autonomos")
def salvar_autonomo(
    id_autonomo: str = Form(""),
    nome_autonomo: str = Form(...),
    cpf: str = Form(""),
    telefone: str = Form(""),
    email: str = Form(""),
    tipo_autonomo: str = Form("Mecanico"),
    especialidade: str = Form(""),
    data_inclusao: str = Form(""),
    status_autonomo: str = Form("Ativo"),
    observacoes: str = Form(""),
    db: Session = Depends(get_db),
):
    autonomo = db.get(DimAutonomo, int(id_autonomo)) if id_autonomo else DimAutonomo()
    autonomo.nome_autonomo = nome_autonomo
    autonomo.cpf = cpf
    autonomo.telefone = telefone
    autonomo.email = email
    autonomo.tipo_autonomo = tipo_autonomo
    autonomo.especialidade = especialidade
    autonomo.data_inclusao = parse_date(data_inclusao) or autonomo.data_inclusao
    autonomo.status_autonomo = status_autonomo
    autonomo.observacoes = observacoes
    db.add(autonomo)
    db.commit()
    return redirect_with_message("/autonomos", success="Autonomo salvo com sucesso.")


@router.post("/autonomos/{id_autonomo}/desligar")
def desligar_autonomo(id_autonomo: int, data_saida: str = Form(...), motivo: str = Form(...), db: Session = Depends(get_db)):
    autonomo = db.get(DimAutonomo, id_autonomo)
    if not autonomo:
        return redirect_with_message("/autonomos", error="Autonomo nao encontrado.")
    autonomo.status_autonomo = "Desligado"
    autonomo.data_saida = parse_date(data_saida)
    autonomo.motivo_saida = motivo
    db.commit()
    return redirect_with_message("/autonomos", success="Autonomo desligado sem exclusao fisica.")


@router.get("/etapas")
def etapas(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("cadastros/etapas.html", {"request": request, "items": db.query(DimEtapa).order_by(DimEtapa.temporada.desc(), DimEtapa.nome_etapa).all(), **flash_from_request(request)})


@router.post("/etapas")
def salvar_etapa(
    temporada: str = Form(...),
    nome_etapa: str = Form(...),
    local: str = Form(""),
    data_inicio: str = Form(""),
    data_fim: str = Form(""),
    status_etapa: str = Form("Planejada"),
    observacoes: str = Form(""),
    db: Session = Depends(get_db),
):
    db.add(DimEtapa(temporada=temporada, nome_etapa=nome_etapa, local=local, data_inicio=parse_date(data_inicio), data_fim=parse_date(data_fim), status_etapa=status_etapa, observacoes=observacoes))
    db.commit()
    return redirect_with_message("/etapas", success="Etapa cadastrada.")


@router.get("/provas")
def provas(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("cadastros/provas.html", {"request": request, "items": db.query(DimProva).order_by(DimProva.data_prova.desc()).all(), **lists(db), **flash_from_request(request)})


@router.post("/provas")
def salvar_prova(id_etapa: int = Form(...), id_tipo_prova: int = Form(...), nome_prova: str = Form(...), data_prova: str = Form(""), status_prova: str = Form("Planejada"), observacoes: str = Form(""), db: Session = Depends(get_db)):
    db.add(DimProva(id_etapa=id_etapa, id_tipo_prova=id_tipo_prova, nome_prova=nome_prova, data_prova=parse_date(data_prova), status_prova=status_prova, observacoes=observacoes))
    db.commit()
    return redirect_with_message("/provas", success="Prova cadastrada.")


@router.get("/tipos-prova")
def tipos_prova(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("cadastros/tipos.html", {"request": request, "items": db.query(DimTipoProva).order_by(DimTipoProva.nome_tipo_prova).all(), **flash_from_request(request)})


@router.post("/tipos-prova")
def salvar_tipo(nome_tipo_prova: str = Form(...), descricao: str = Form(""), status_tipo_prova: str = Form("Ativo"), db: Session = Depends(get_db)):
    db.add(DimTipoProva(nome_tipo_prova=nome_tipo_prova, descricao=descricao, status_tipo_prova=status_tipo_prova))
    db.commit()
    return redirect_with_message("/tipos-prova", success="Tipo de prova cadastrado.")


@router.get("/motivos-troca")
def motivos_troca(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("cadastros/motivos.html", {"request": request, "items": db.query(DimMotivoTroca).order_by(DimMotivoTroca.motivo_troca).all(), **flash_from_request(request)})


@router.post("/motivos-troca")
def salvar_motivo(motivo_troca: str = Form(...), descricao: str = Form(""), status: str = Form("Ativo"), db: Session = Depends(get_db)):
    db.add(DimMotivoTroca(motivo_troca=motivo_troca, descricao=descricao, status=status))
    db.commit()
    return redirect_with_message("/motivos-troca", success="Motivo cadastrado.")
