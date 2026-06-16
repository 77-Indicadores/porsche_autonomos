from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import DimCargoAutonomo, FatoPilotoAutonomoProva
from app.routers.alocacoes import conflito_ativo, options
from app.template_config import templates
from app.utils import flash_from_request, parse_money, redirect_with_message

router = APIRouter(tags=["wizard"])


@router.get("/operacao/nova-guiada")
def nova_guiada(request: Request, db: Session = Depends(get_db)):
    ativos = (
        db.query(FatoPilotoAutonomoProva)
        .filter(FatoPilotoAutonomoProva.status_vinculo == "Ativo")
        .order_by(FatoPilotoAutonomoProva.id_fato.desc())
        .all()
    )

    return templates.TemplateResponse(
        "operacao/nova_guiada.html",
        {
            "request": request,
            "ativos": ativos,
            "today": date.today(),
            **options(db),
            **flash_from_request(request),
        },
    )


@router.post("/operacao/nova-guiada")
def criar_guiada(
    id_etapa: int = Form(...),
    id_prova: int = Form(...),
    id_piloto: int = Form(...),
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
        return redirect_with_message("/operacao/nova-guiada", error="Cargo não encontrado.")

    funcao_autonomo = cargo.nome_cargo
    valor = parse_money(valor_fechado_etapa)

    dias = None
    if dias_trabalhados:
        try:
            dias = int(dias_trabalhados)
        except Exception:
            return redirect_with_message("/operacao/nova-guiada", error="Dias trabalhados deve ser número inteiro.")

        if dias <= 0:
            return redirect_with_message("/operacao/nova-guiada", error="Dias trabalhados deve ser maior que zero.")

    if tipo_alocacao == "Substituição":
        if not id_fato_substituido:
            return redirect_with_message("/operacao/nova-guiada", error="Informe quem será substituído.")

        if not id_motivo_troca:
            return redirect_with_message("/operacao/nova-guiada", error="Informe o motivo da troca.")

        anterior = db.get(FatoPilotoAutonomoProva, int(id_fato_substituido))

        if not anterior:
            return redirect_with_message("/operacao/nova-guiada", error="Alocação anterior não encontrada.")
        if anterior.id_piloto != id_piloto or anterior.id_prova != id_prova or (anterior.funcao_autonomo or "") != funcao_autonomo:
            return redirect_with_message("/operacao/nova-guiada", error="Substituicao inconsistente com piloto, categoria ou cargo selecionado.")

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
                "/operacao/nova-guiada",
                error="Já existe autônomo ativo para este piloto, categoria e cargo. Use substituição.",
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
