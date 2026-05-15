from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import DimCarro, DimCargoAutonomo, DimAutonomo, DimEtapa, DimMotivoTroca, DimPiloto, DimProva, FatoPilotoAutonomoProva
from app.template_config import templates
from app.utils import flash_from_request, parse_date, parse_money, redirect_with_message

router = APIRouter(tags=["alocacoes"])


def options(db: Session):
    return {
        "pilotos": db.query(DimPiloto).filter(DimPiloto.status_piloto == "Ativo").order_by(DimPiloto.nome_piloto).all(),
        "autonomos": db.query(DimAutonomo).filter(DimAutonomo.status_autonomo == "Ativo").order_by(DimAutonomo.nome_autonomo).all(),
        "carros": db.query(DimCarro).filter(DimCarro.status_carro == "Ativo").order_by(DimCarro.numero_carro).all(),
        "cargos_autonomos": db.query(DimCargoAutonomo).filter(DimCargoAutonomo.status == "Ativo").order_by(DimCargoAutonomo.nome_cargo).all(),
        "etapas": db.query(DimEtapa).order_by(DimEtapa.temporada.desc(), DimEtapa.nome_etapa).all(),
        "provas": db.query(DimProva).order_by(DimProva.data_prova.desc()).all(),
        "motivos": db.query(DimMotivoTroca).filter(DimMotivoTroca.status == "Ativo").order_by(DimMotivoTroca.motivo_troca).all(),
        "ativos": db.query(FatoPilotoAutonomoProva).filter(FatoPilotoAutonomoProva.status_vinculo == "Ativo").order_by(FatoPilotoAutonomoProva.id_fato.desc()).all(),
    }


def conflito_ativo(db: Session, id_piloto: int, id_prova: int, funcao_autonomo: str, ignore_id: int | None = None):
    query = db.query(FatoPilotoAutonomoProva).filter(
        FatoPilotoAutonomoProva.id_piloto == id_piloto,
        FatoPilotoAutonomoProva.id_prova == id_prova,
        FatoPilotoAutonomoProva.funcao_autonomo == funcao_autonomo,
        FatoPilotoAutonomoProva.status_vinculo == "Ativo",
    )
    if ignore_id:
        query = query.filter(FatoPilotoAutonomoProva.id_fato != ignore_id)
    return query.first()


@router.get("/alocacoes")
def index(request: Request, id_etapa: str = "", id_prova: str = "", status: str = "", db: Session = Depends(get_db)):
    query = db.query(FatoPilotoAutonomoProva)
    if id_etapa:
        try:
            query = query.filter(FatoPilotoAutonomoProva.id_etapa == int(id_etapa))
        except ValueError:
            return redirect_with_message("/alocacoes", error="Filtro de etapa invalido.")
    if id_prova:
        try:
            query = query.filter(FatoPilotoAutonomoProva.id_prova == int(id_prova))
        except ValueError:
            return redirect_with_message("/alocacoes", error="Filtro de categoria invalido.")
    if status:
        query = query.filter(FatoPilotoAutonomoProva.status_vinculo == status)
    fatos = query.order_by(FatoPilotoAutonomoProva.status_vinculo, FatoPilotoAutonomoProva.id_fato.desc()).all()
    return templates.TemplateResponse("alocacoes/list.html", {"request": request, "fatos": fatos, "filtros": {"id_etapa": id_etapa, "id_prova": id_prova, "status": status}, **options(db), **flash_from_request(request)})


@router.get("/alocacoes/nova")
def nova(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("alocacoes/form.html", {"request": request, "today": date.today(), **options(db), **flash_from_request(request)})


@router.post("/alocacoes/nova")
def criar(
    id_piloto: int = Form(...),
    id_etapa: int = Form(...),
    id_prova: int = Form(...),
    id_carro: int = Form(...),
    id_cargo_autonomo: int = Form(...),
    id_autonomo: int = Form(...),
    tipo_alocacao: str = Form("Formar equipe"),
    id_fato_substituido: str = Form(""),
    id_motivo_troca: str = Form(""),
    justificativa_troca: str = Form(""),
    valor_fechado_etapa: str = Form(""),
    dias_trabalhados: str = Form(""),
    observacoes: str = Form(""),
    db: Session = Depends(get_db),
):
    cargo = db.get(DimCargoAutonomo, id_cargo_autonomo)

    if not cargo:
        return redirect_with_message("/alocacoes/nova", error="Cargo não encontrado.")

    funcao_autonomo = cargo.nome_cargo
    valor = parse_money(valor_fechado_etapa)

    dias = None
    if dias_trabalhados:
        try:
            dias = int(dias_trabalhados)
        except Exception:
            return redirect_with_message("/alocacoes/nova", error="Dias trabalhados deve ser número inteiro.")

        if dias <= 0:
            return redirect_with_message("/alocacoes/nova", error="Dias trabalhados deve ser maior que zero.")

    if tipo_alocacao == "Substituição":
        if not id_fato_substituido:
            return redirect_with_message("/alocacoes/nova", error="Informe quem será substituído.")

        if not id_motivo_troca:
            return redirect_with_message("/alocacoes/nova", error="Informe o motivo da troca.")

        anterior = db.get(FatoPilotoAutonomoProva, int(id_fato_substituido))

        if not anterior:
            return redirect_with_message("/alocacoes/nova", error="Alocação anterior não encontrada.")
        if anterior.id_piloto != id_piloto or anterior.id_prova != id_prova or (anterior.funcao_autonomo or "") != funcao_autonomo:
            return redirect_with_message("/alocacoes/nova", error="Substituicao inconsistente com piloto, categoria ou cargo selecionado.")

        data_troca = date.today()

        anterior.status_vinculo = "Substituido"
        anterior.foi_substituido = "Sim"
        anterior.id_autonomo_substituto = id_autonomo
        anterior.data_troca = data_troca
        anterior.data_fim_vinculo = data_troca
        anterior.id_motivo_troca = int(id_motivo_troca)
        anterior.justificativa_troca = justificativa_troca

    else:
        conflito = conflito_ativo(db, id_piloto, id_prova, funcao_autonomo)

        if conflito:
            return redirect_with_message(
                "/alocacoes/nova",
                error="Já existe autônomo ativo para este piloto, categoria e cargo. Use Substituição.",
            )

    fato = FatoPilotoAutonomoProva(
        id_piloto=id_piloto,
        id_autonomo=id_autonomo,
        id_etapa=id_etapa,
        id_prova=id_prova,
        id_carro=id_carro,
        funcao_autonomo=funcao_autonomo,
        data_inicio_vinculo=date.today(),
        status_vinculo="Ativo",
        valor_fechado_etapa=valor,
        dias_trabalhados=dias,
        status_pagamento=None,
        observacoes=observacoes,
    )

    db.add(fato)
    db.commit()

    return redirect_with_message("/alocacoes", success="Alocação salva com sucesso.")


@router.get("/alocacoes/{id_fato}/substituir")
def substituir_form(id_fato: int, request: Request, db: Session = Depends(get_db)):
    fato = db.get(FatoPilotoAutonomoProva, id_fato)
    if not fato:
        return redirect_with_message("/alocacoes", error="Alocacao nao encontrada.")
    return templates.TemplateResponse("alocacoes/substituir.html", {"request": request, "fato": fato, "today": date.today(), **options(db), **flash_from_request(request)})


@router.post("/alocacoes/{id_fato}/substituir")
def substituir(
    id_fato: int,
    id_autonomo_substituto: int = Form(...),
    data_troca: str = Form(...),
    id_motivo_troca: int = Form(...),
    justificativa_troca: str = Form(...),
    valor_fechado_etapa: str = Form(""),
    observacoes: str = Form(""),
    db: Session = Depends(get_db),
):
    fato = db.get(FatoPilotoAutonomoProva, id_fato)
    if not fato or fato.status_vinculo != "Ativo":
        return redirect_with_message("/alocacoes", error="Somente alocacao ativa pode ser substituida.")
    try:
        data = parse_date(data_troca)
    except ValueError:
        return redirect_with_message("/alocacoes", error="Data de troca invalida.")
    if not data:
        return redirect_with_message("/alocacoes", error="Data de troca invalida.")
    fato.status_vinculo = "Substituido"
    fato.foi_substituido = "Sim"
    fato.id_autonomo_substituto = id_autonomo_substituto
    fato.data_troca = data
    fato.data_fim_vinculo = data
    fato.id_motivo_troca = id_motivo_troca
    fato.justificativa_troca = justificativa_troca
    novo = FatoPilotoAutonomoProva(
        id_piloto=fato.id_piloto,
        id_autonomo=id_autonomo_substituto,
        id_etapa=fato.id_etapa,
        id_prova=fato.id_prova,
        id_carro=fato.id_carro,
        funcao_autonomo=fato.funcao_autonomo,
        data_inicio_vinculo=data,
        status_vinculo="Ativo",
        valor_fechado_etapa=parse_money(valor_fechado_etapa),
        dias_trabalhados=fato.dias_trabalhados,
        observacoes=observacoes,
    )
    db.add(novo)
    db.commit()
    return redirect_with_message("/alocacoes", success="Substituicao registrada e historico preservado.")


@router.get("/alocacoes/{id_fato}/avaliar")
def avaliar_form(id_fato: int, request: Request, db: Session = Depends(get_db)):
    fato = db.get(FatoPilotoAutonomoProva, id_fato)
    if not fato:
        return redirect_with_message("/alocacoes", error="Alocacao nao encontrada.")
    return templates.TemplateResponse("alocacoes/avaliar.html", {"request": request, "fato": fato, "today": date.today(), **flash_from_request(request)})


@router.post("/alocacoes/{id_fato}/avaliar")
def avaliar(id_fato: int, nota_tecnica: str = Form(...), nota_pontualidade: str = Form(...), nota_comunicacao: str = Form(...), nota_relacionamento: str = Form(...), nota_geral: str = Form(""), comentario_avaliacao: str = Form(""), data_avaliacao: str = Form(...), db: Session = Depends(get_db)):
    fato = db.get(FatoPilotoAutonomoProva, id_fato)
    if not fato:
        return redirect_with_message("/alocacoes", error="Alocacao nao encontrada.")
    try:
        notas = [float(nota_tecnica), float(nota_pontualidade), float(nota_comunicacao), float(nota_relacionamento)]
    except ValueError:
        return redirect_with_message(f"/alocacoes/{id_fato}/avaliar", error="Notas invalidas. Use apenas numeros.")
    fato.nota_tecnica, fato.nota_pontualidade, fato.nota_comunicacao, fato.nota_relacionamento = notas
    try:
        fato.nota_geral = float(nota_geral) if nota_geral else round(sum(notas) / 4, 2)
    except ValueError:
        return redirect_with_message(f"/alocacoes/{id_fato}/avaliar", error="Nota geral invalida.")
    fato.comentario_avaliacao = comentario_avaliacao
    try:
        data = parse_date(data_avaliacao)
    except ValueError:
        return redirect_with_message(f"/alocacoes/{id_fato}/avaliar", error="Data de avaliacao invalida.")
    if not data:
        return redirect_with_message(f"/alocacoes/{id_fato}/avaliar", error="Data de avaliacao invalida.")
    fato.data_avaliacao = data
    db.commit()
    return redirect_with_message("/alocacoes", success="Avaliacao salva.")


@router.get("/alocacoes/{id_fato}/custo")
def custo_form(id_fato: int, request: Request, db: Session = Depends(get_db)):
    fato = db.get(FatoPilotoAutonomoProva, id_fato)
    if not fato:
        return redirect_with_message("/alocacoes", error="Alocacao nao encontrada.")
    return templates.TemplateResponse("alocacoes/custo.html", {"request": request, "fato": fato, **options(db), **flash_from_request(request)})


@router.post("/alocacoes/{id_fato}/custo")
def custo(
    id_fato: int,
    valor_fechado_etapa: str = Form(""),
    dias_trabalhados: str = Form(""),
    documento: str = Form(""),
    observacoes: str = Form(""),
    db: Session = Depends(get_db),
):
    fato = db.get(FatoPilotoAutonomoProva, id_fato)

    if not fato:
        return redirect_with_message("/alocacoes", error="Alocação não encontrada.")

    dias = None
    if dias_trabalhados:
        try:
            dias = int(dias_trabalhados)
        except Exception:
            return redirect_with_message(f"/alocacoes/{id_fato}/custo", error="Dias trabalhados deve ser um número inteiro.")

        if dias <= 0:
            return redirect_with_message(f"/alocacoes/{id_fato}/custo", error="Dias trabalhados deve ser maior que zero.")

    fato.valor_fechado_etapa = parse_money(valor_fechado_etapa)
    fato.dias_trabalhados = dias
    fato.status_pagamento = None
    fato.data_pagamento = None
    fato.documento = documento
    fato.observacoes = observacoes

    db.commit()

    return redirect_with_message("/alocacoes", success="Pacote atualizado.")


@router.post("/alocacoes/{id_fato}/encerrar")
def encerrar(id_fato: int, data_fim: str = Form(...), motivo: str = Form("Encerramento manual"), db: Session = Depends(get_db)):
    fato = db.get(FatoPilotoAutonomoProva, id_fato)
    if not fato:
        return redirect_with_message("/alocacoes", error="Alocacao nao encontrada.")
    try:
        data = parse_date(data_fim)
    except ValueError:
        return redirect_with_message("/alocacoes", error="Data de encerramento invalida.")
    if not data:
        return redirect_with_message("/alocacoes", error="Data de encerramento invalida.")
    fato.status_vinculo = "Encerrado"
    fato.data_fim_vinculo = data
    fato.justificativa_troca = motivo
    db.commit()
    return redirect_with_message("/alocacoes", success="Vinculo encerrado.")



