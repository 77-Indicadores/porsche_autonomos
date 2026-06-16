from pathlib import Path
import uuid
import shutil
from fastapi import APIRouter, Depends, Form, Request, UploadFile, File
from sqlalchemy import or_, text
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import DimCargoAutonomo, DimAutonomo, DimEtapa, DimMotivoTroca, DimPiloto, DimProva, DimTipoProva, FatoPilotoAutonomoProva
from app.template_config import templates
from app.utils import flash_from_request, parse_date, redirect_with_message

router = APIRouter(tags=["cadastros"])


UPLOAD_BASE = Path(__file__).resolve().parents[1] / "static" / "uploads"

def salvar_upload_foto(arquivo: UploadFile, pasta: str):
    if not arquivo or not arquivo.filename:
        return None

    extensao = Path(arquivo.filename).suffix.lower()

    if extensao not in [".jpg", ".jpeg", ".png", ".webp"]:
        return None

    destino_dir = UPLOAD_BASE / pasta
    destino_dir.mkdir(parents=True, exist_ok=True)

    nome_arquivo = f"{uuid.uuid4().hex}{extensao}"
    destino = destino_dir / nome_arquivo

    with destino.open("wb") as buffer:
        shutil.copyfileobj(arquivo.file, buffer)

    return f"/static/uploads/{pasta}/{nome_arquivo}"



def lists(db: Session):
    return {
        "pilotos": db.query(DimPiloto).order_by(DimPiloto.nome_piloto).all(),
        "autonomos": db.query(DimAutonomo).order_by(DimAutonomo.nome_autonomo).all(),
        "etapas": db.query(DimEtapa).order_by(DimEtapa.temporada.desc(), DimEtapa.nome_etapa).all(),
        "tipos": db.query(DimTipoProva).order_by(DimTipoProva.nome_tipo_prova).all(),
        "motivos": db.query(DimMotivoTroca).order_by(DimMotivoTroca.motivo_troca).all(),
        "cargos_autonomos": db.query(DimCargoAutonomo).filter(DimCargoAutonomo.status == "Ativo").order_by(DimCargoAutonomo.nome_cargo).all(),
    }


@router.get("/pilotos")
def pilotos(request: Request, q: str = "", db: Session = Depends(get_db)):
    query = db.query(DimPiloto)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(DimPiloto.nome_piloto.ilike(like), DimPiloto.status_piloto.ilike(like)))
    return templates.TemplateResponse("cadastros/pilotos.html", {"request": request, "items": query.order_by(DimPiloto.nome_piloto).all(), "q": q, **flash_from_request(request)})


@router.post("/pilotos")
def salvar_piloto(
    id_piloto: str = Form(""),
    nome_piloto: str = Form(...),
    cpf: str = Form(""),
    telefone: str = Form(""),
    email: str = Form(""),
    data_inclusao: str = Form(""),
    status_piloto: str = Form("Ativo"),
    observacoes: str = Form(""),
    foto_url: str = Form(""),
    foto_upload: UploadFile = File(None),
    db: Session = Depends(get_db),
):
    piloto = db.get(DimPiloto, int(id_piloto)) if id_piloto else DimPiloto()
    piloto.nome_piloto = nome_piloto
    piloto.cpf = cpf
    piloto.telefone = telefone
    piloto.email = email
    piloto.data_inclusao = parse_date(data_inclusao) or piloto.data_inclusao
    piloto.status_piloto = status_piloto
    piloto.observacoes = observacoes
    foto_salva = salvar_upload_foto(foto_upload, "pilotos")

    if foto_salva:
        piloto.foto_url = foto_salva
    elif foto_url:
        piloto.foto_url = foto_url
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
    return templates.TemplateResponse("cadastros/autonomos.html", {"request": request, "items": query.order_by(DimAutonomo.nome_autonomo).all(), "q": q, **lists(db), **flash_from_request(request)})


@router.post("/autonomos")
def salvar_autonomo(
    id_autonomo: str = Form(""),
    nome_autonomo: str = Form(...),
    cpf: str = Form(""),
    telefone: str = Form(""),
    email: str = Form(""),
    tipo_autonomo: str = Form(""),
    id_cargo_autonomo: str = Form(""),
    especialidade: str = Form(""),
    data_inclusao: str = Form(""),
    status_autonomo: str = Form("Ativo"),
    observacoes: str = Form(""),
    foto_url: str = Form(""),
    foto_upload: UploadFile = File(None),
    db: Session = Depends(get_db),
):
    autonomo = db.get(DimAutonomo, int(id_autonomo)) if id_autonomo else DimAutonomo()
    autonomo.nome_autonomo = nome_autonomo
    autonomo.cpf = cpf
    autonomo.telefone = telefone
    autonomo.email = email

    cargo_obj = db.get(DimCargoAutonomo, int(id_cargo_autonomo)) if id_cargo_autonomo else None
    autonomo.id_cargo_autonomo = int(id_cargo_autonomo) if id_cargo_autonomo else None
    autonomo.tipo_autonomo = cargo_obj.nome_cargo if cargo_obj else tipo_autonomo
    autonomo.especialidade = especialidade
    autonomo.data_inclusao = parse_date(data_inclusao) or autonomo.data_inclusao
    autonomo.status_autonomo = status_autonomo
    autonomo.observacoes = observacoes

    foto_salva = salvar_upload_foto(foto_upload, "autonomos")

    if foto_salva:
        autonomo.foto_url = foto_salva
    elif foto_url:
        autonomo.foto_url = foto_url
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
    foto_url: str = Form(""),
    foto_upload: UploadFile = File(None),
    db: Session = Depends(get_db),
):
    db.add(DimEtapa(temporada=temporada, nome_etapa=nome_etapa, local=local, data_inicio=parse_date(data_inicio), data_fim=parse_date(data_fim), status_etapa=status_etapa, observacoes=observacoes))
    db.commit()
    return redirect_with_message("/etapas", success="Etapa cadastrada.")


@router.get("/categorias")
@router.get("/provas")
def provas(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("cadastros/provas.html", {"request": request, "items": db.query(DimProva).order_by(DimProva.data_prova.desc()).all(), **lists(db), **flash_from_request(request)})


@router.post("/categorias")
@router.post("/provas")
def salvar_prova(id_etapa: int = Form(...), id_tipo_prova: int = Form(...), nome_prova: str = Form(...), data_prova: str = Form(""), status_prova: str = Form("Planejada"), observacoes: str = Form(""), db: Session = Depends(get_db)):
    db.add(DimProva(id_etapa=id_etapa, id_tipo_prova=id_tipo_prova, nome_prova=nome_prova, data_prova=parse_date(data_prova), status_prova=status_prova, observacoes=observacoes))
    db.commit()
    return redirect_with_message("/categorias", success="Categoria cadastrada.")


@router.get("/tipos-categoria")
@router.get("/tipos-prova")
def tipos_prova(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("cadastros/tipos.html", {"request": request, "items": db.query(DimTipoProva).order_by(DimTipoProva.nome_tipo_prova).all(), **flash_from_request(request)})


@router.post("/tipos-categoria")
@router.post("/tipos-prova")
def salvar_tipo(
    id_tipo_prova: str = Form(""),
    nome_tipo_prova: str = Form(...),
    descricao: str = Form(""),
    status_tipo_prova: str = Form("Ativo"),
    db: Session = Depends(get_db),
):
    tipo = db.get(DimTipoProva, int(id_tipo_prova)) if id_tipo_prova else DimTipoProva()

    if not tipo:
        return redirect_with_message("/tipos-prova", error="Tipo de prova não encontrado.")

    tipo.nome_tipo_prova = nome_tipo_prova
    tipo.descricao = descricao
    tipo.status_tipo_prova = status_tipo_prova

    db.add(tipo)
    db.commit()

    msg = "Tipo de prova atualizado." if id_tipo_prova else "Tipo de prova cadastrado."
    return redirect_with_message("/tipos-prova", success=msg)


@router.get("/motivos-troca")
def motivos_troca(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("cadastros/motivos.html", {"request": request, "items": db.query(DimMotivoTroca).order_by(DimMotivoTroca.motivo_troca).all(), **flash_from_request(request)})


@router.post("/motivos-troca")
def salvar_motivo(
    id_motivo_troca: str = Form(""),
    motivo_troca: str = Form(...),
    descricao: str = Form(""),
    status: str = Form("Ativo"),
    db: Session = Depends(get_db),
):
    motivo = db.get(DimMotivoTroca, int(id_motivo_troca)) if id_motivo_troca else DimMotivoTroca()

    if not motivo:
        return redirect_with_message("/motivos-troca", error="Motivo de troca não encontrado.")

    motivo.motivo_troca = motivo_troca
    motivo.descricao = descricao
    motivo.status = status

    db.add(motivo)
    db.commit()

    msg = "Motivo de troca atualizado." if id_motivo_troca else "Motivo cadastrado."
    return redirect_with_message("/motivos-troca", success=msg)


@router.get("/cargos-autonomos")
def cargos_autonomos(request: Request, db: Session = Depends(get_db)):
    items = db.query(DimCargoAutonomo).order_by(DimCargoAutonomo.nome_cargo).all()

    return templates.TemplateResponse(
        "cadastros/cargos_autonomos.html",
        {
            "request": request,
            "items": items,
            **flash_from_request(request),
        },
    )


@router.post("/cargos-autonomos")
def salvar_cargo_autonomo(
    id_cargo_autonomo: str = Form(""),
    nome_cargo: str = Form(...),
    descricao: str = Form(""),
    status: str = Form("Ativo"),
    db: Session = Depends(get_db),
):
    cargo = db.get(DimCargoAutonomo, int(id_cargo_autonomo)) if id_cargo_autonomo else DimCargoAutonomo()

    if not cargo:
        return redirect_with_message("/cargos-autonomos", error="Cargo não encontrado.")

    cargo.nome_cargo = nome_cargo
    cargo.descricao = descricao
    cargo.status = status

    db.add(cargo)
    db.commit()

    msg = "Cargo atualizado." if id_cargo_autonomo else "Cargo cadastrado."
    return redirect_with_message("/cargos-autonomos", success=msg)

