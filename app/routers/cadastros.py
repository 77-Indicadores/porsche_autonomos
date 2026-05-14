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



def aplicar_id_manual(db: Session, obj, model, pk_name: str, novo_id: str, atual_id: str = ""):
    """
    Permite informar ID manualmente no cadastro.
    - Novo registro sem ID: banco gera automático.
    - Novo registro com ID: usa o ID informado, se não existir.
    - Edição sem troca: mantém ID.
    - Edição com troca: altera PK, se o novo ID não existir.
    """
    novo_id = str(novo_id or "").strip()
    atual_id = str(atual_id or "").strip()

    if not novo_id:
        return obj

    try:
        novo = int(novo_id)
    except Exception:
        raise ValueError(f"ID inválido: {novo_id}")

    atual = None
    if atual_id:
        try:
            atual = int(atual_id)
        except Exception:
            atual = None

    existente = db.get(model, novo)

    if existente and (not atual or novo != atual):
        raise ValueError(f"ID {novo} já existe.")

    setattr(obj, pk_name, novo)
    return obj


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
    current_id_piloto: str = "",
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
    piloto = db.get(DimPiloto, int(current_id_piloto or id_piloto)) if (current_id_piloto or id_piloto) else DimPiloto()
    try:
        aplicar_id_manual(db, piloto, DimPiloto, "id_piloto", id_piloto, current_id_piloto)
    except ValueError as e:
        return redirect_with_message("/pilotos", error=str(e))
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
def desligar_piloto(id_piloto: int, data_desligamento: str = Form(...), motivo_desligamento: str = Form(...), db: Session = Depends(get_db)):
    piloto = db.get(DimPiloto, id_piloto)
    if not piloto:
        return redirect_with_message("/pilotos", error="Piloto nao encontrado.")
    piloto.status_piloto = "Desligado"
    piloto.data_desligamento = parse_date(data_desligamento)
    piloto.motivo_desligamento = motivo_desligamento_desligamento
    db.commit()
    return redirect_with_message("/pilotos", success="Piloto desligado sem exclusao fisica.")


@router.get("/autonomos")
def autonomos(request: Request, q: str = "", db: Session = Depends(get_db)):
    query = db.query(DimAutonomo)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(DimAutonomo.nome_autonomo.ilike(like), DimAutonomo.tipo_autonomo.ilike(like), DimAutonomo.status_autonomo.ilike(like)))
    return templates.TemplateResponse("cadastros/autonomos.html", {"request": request, "items": query.order_by(DimAutonomo.nome_autonomo).all(), "q": q, **lists(db), **flash_from_request(request)})


@router.post("/autonomos")
def salvar_autonomo(
    id_autonomo: str = Form(""),
    current_id_autonomo: str = "",
    nome_autonomo: str = Form(...),
    cpf: str = Form(""),
    telefone: str = Form(""),
    email: str = Form(""),
    tipo_autonomo: str = Form(""),
    id_cargo_autonomo: str = Form(""),
    data_inclusao: str = Form(""),
    status_autonomo: str = Form("Ativo"),
    observacoes: str = Form(""),
    foto_url: str = Form(""),
    foto_upload: UploadFile = File(None),
    db: Session = Depends(get_db),
):
    autonomo = db.get(DimAutonomo, int(current_id_autonomo or id_autonomo)) if (current_id_autonomo or id_autonomo) else DimAutonomo()
    try:
        aplicar_id_manual(db, autonomo, DimAutonomo, "id_autonomo", id_autonomo, current_id_autonomo)
    except ValueError as e:
        return redirect_with_message("/autonomos", error=str(e))
    autonomo.nome_autonomo = nome_autonomo
    autonomo.cpf = cpf
    autonomo.telefone = telefone
    autonomo.email = email

    cargo_obj = db.get(DimCargoAutonomo, int(id_cargo_autonomo)) if id_cargo_autonomo else None
    autonomo.id_cargo_autonomo = int(id_cargo_autonomo) if id_cargo_autonomo else None
    autonomo.tipo_autonomo = cargo_obj.nome_cargo if cargo_obj else tipo_autonomo
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
def desligar_autonomo(id_autonomo: int, data_saida: str = Form(...), motivo_saida: str = Form(...), db: Session = Depends(get_db)):
    autonomo = db.get(DimAutonomo, id_autonomo)
    if not autonomo:
        return redirect_with_message("/autonomos", error="Autonomo nao encontrado.")
    autonomo.status_autonomo = "Desligado"
    autonomo.data_saida = parse_date(data_saida)
    autonomo.motivo_saida = motivo_saida_saida
    db.commit()
    return redirect_with_message("/autonomos", success="Autonomo desligado sem exclusao fisica.")


@router.get("/etapas")
def etapas(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("cadastros/etapas.html", {"request": request, "items": db.query(DimEtapa).order_by(DimEtapa.temporada.desc(), DimEtapa.nome_etapa).all(), **flash_from_request(request)})


@router.post("/etapas")
def salvar_etapa(
    id_etapa: str = Form(""),
    current_id_etapa: str = "",
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
    etapa = db.get(DimEtapa, int(current_id_etapa or id_etapa)) if (current_id_etapa or id_etapa) else DimEtapa()
    try:
        aplicar_id_manual(db, etapa, DimEtapa, "id_etapa", id_etapa, current_id_etapa)
    except ValueError as e:
        return redirect_with_message("/etapas", error=str(e))

    etapa.temporada = temporada
    etapa.nome_etapa = nome_etapa
    etapa.local = local
    etapa.data_inicio = parse_date(data_inicio) or etapa.data_inicio
    etapa.data_fim = parse_date(data_fim) or etapa.data_fim
    etapa.status_etapa = status_etapa
    etapa.observacoes = observacoes

    db.add(etapa)
    db.commit()
    return redirect_with_message("/etapas", success="Etapa salva.")


@router.get("/categorias")
@router.get("/provas")
def provas(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("cadastros/provas.html", {"request": request, "items": db.query(DimProva).order_by(DimProva.data_prova.desc()).all(), **lists(db), **flash_from_request(request)})


@router.post("/categorias")
@router.post("/provas")
def salvar_prova(id_prova: str = Form(""), current_id_prova: str = Form(""), id_etapa: int = Form(...), id_tipo_prova: int = Form(...), nome_prova: str = Form(...), data_prova: str = Form(""), status_prova: str = Form("Planejada"), observacoes: str = Form(""), db: Session = Depends(get_db)):
    prova = db.get(DimProva, int(current_id_prova or id_prova)) if (current_id_prova or id_prova) else DimProva()
    try:
        aplicar_id_manual(db, prova, DimProva, "id_prova", id_prova, current_id_prova)
    except ValueError as e:
        return redirect_with_message("/categorias", error=str(e))

    prova.id_etapa = id_etapa
    prova.id_tipo_prova = id_tipo_prova
    prova.nome_prova = nome_prova
    prova.data_prova = parse_date(data_prova) or prova.data_prova
    prova.status_prova = status_prova
    prova.observacoes = observacoes

    db.add(prova)
    db.commit()
    return redirect_with_message("/categorias", success="Categoria salva.")


@router.get("/tipos-categoria")
@router.get("/tipos-prova")
def tipos_prova(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("cadastros/tipos.html", {"request": request, "items": db.query(DimTipoProva).order_by(DimTipoProva.nome_tipo_prova).all(), **flash_from_request(request)})


@router.post("/tipos-categoria")
@router.post("/tipos-prova")
def salvar_tipo(
    id_tipo_prova: str = Form(""),
    current_id_tipo_prova: str = "",
    nome_tipo_prova: str = Form(...),
    descricao: str = Form(""),
    status_tipo_prova: str = Form("Ativo"),
    db: Session = Depends(get_db),
):
    tipo = db.get(DimTipoProva, int(current_id_tipo_prova or id_tipo_prova)) if (current_id_tipo_prova or id_tipo_prova) else DimTipoProva()
    try:
        aplicar_id_manual(db, tipo, DimTipoProva, "id_tipo_prova", id_tipo_prova, current_id_tipo_prova)
    except ValueError as e:
        return redirect_with_message("/tipos-prova", error=str(e))

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
    current_id_motivo_troca: str = "",
    motivo_troca: str = Form(...),
    descricao: str = Form(""),
    status: str = Form("Ativo"),
    db: Session = Depends(get_db),
):
    motivo = db.get(DimMotivoTroca, int(current_id_motivo_troca or id_motivo_troca)) if (current_id_motivo_troca or id_motivo_troca) else DimMotivoTroca()
    try:
        aplicar_id_manual(db, motivo, DimMotivoTroca, "id_motivo_troca", id_motivo_troca, current_id_motivo_troca)
    except ValueError as e:
        return redirect_with_message("/motivos-troca", error=str(e))

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
    current_id_cargo_autonomo: str = "",
    nome_cargo: str = Form(...),
    descricao: str = Form(""),
    status: str = Form("Ativo"),
    db: Session = Depends(get_db),
):
    cargo = db.get(DimCargoAutonomo, int(current_id_cargo_autonomo or id_cargo_autonomo)) if (current_id_cargo_autonomo or id_cargo_autonomo) else DimCargoAutonomo()
    try:
        aplicar_id_manual(db, cargo, DimCargoAutonomo, "id_cargo_autonomo", id_cargo_autonomo, current_id_cargo_autonomo)
    except ValueError as e:
        return redirect_with_message("/cargos-autonomos", error=str(e))

    if not cargo:
        return redirect_with_message("/cargos-autonomos", error="Cargo não encontrado.")

    cargo.nome_cargo = nome_cargo
    cargo.descricao = descricao
    cargo.status = status

    db.add(cargo)
    db.commit()

    msg = "Cargo atualizado." if id_cargo_autonomo else "Cargo cadastrado."
    return redirect_with_message("/cargos-autonomos", success=msg)

