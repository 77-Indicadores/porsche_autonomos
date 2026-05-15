from collections import OrderedDict

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import DimEtapa, DimProva, FatoPilotoAutonomoProva
from app.template_config import templates

router = APIRouter(tags=["equipes"])


@router.get("/equipes")
def equipes(
    request: Request,
    id_etapa: int | None = None,
    id_prova: int | None = None,
    db: Session = Depends(get_db),
):
    etapas = db.query(DimEtapa).order_by(DimEtapa.nome_etapa).all()
    categorias = db.query(DimProva).order_by(DimProva.nome_prova).all()

    query = (
        db.query(FatoPilotoAutonomoProva)
        .options(
            joinedload(FatoPilotoAutonomoProva.piloto),
            joinedload(FatoPilotoAutonomoProva.autonomo),
            joinedload(FatoPilotoAutonomoProva.autonomo_substituto),
            joinedload(FatoPilotoAutonomoProva.etapa),
            joinedload(FatoPilotoAutonomoProva.prova),
            joinedload(FatoPilotoAutonomoProva.carro),
            joinedload(FatoPilotoAutonomoProva.motivo_troca),
        )
    )

    if id_etapa:
        query = query.filter(FatoPilotoAutonomoProva.id_etapa == id_etapa)

    if id_prova:
        query = query.filter(FatoPilotoAutonomoProva.id_prova == id_prova)

    fatos = query.order_by(
        FatoPilotoAutonomoProva.id_etapa,
        FatoPilotoAutonomoProva.id_prova,
        FatoPilotoAutonomoProva.id_piloto,
        FatoPilotoAutonomoProva.id_carro,
        FatoPilotoAutonomoProva.funcao_autonomo,
    ).all()

    equipes_map = OrderedDict()

    for f in fatos:
        chave = (f.id_etapa, f.id_prova, f.id_piloto, f.id_carro)

        if chave not in equipes_map:
            equipes_map[chave] = {
                "piloto": f.piloto,
                "etapa": f.etapa,
                "categoria": f.prova,
                "carro": f.carro,
                "membros": [],
                "substituicoes": [],
                "custo_total": 0.0,
                "qtd_membros": 0,
                "teve_troca": False,
            }

        equipe = equipes_map[chave]

        valor = float(f.valor_fechado_etapa or 0)
        dias = int(f.dias_trabalhados or 0)
        valor_dia = float(f.valor_dia or 0)

        equipe["membros"].append({
            "funcao": f.funcao_autonomo or "-",
            "nome": getattr(f.autonomo, "nome_autonomo", "-"),
            "valor": valor,
            "dias": dias,
            "valor_dia": valor_dia,
            "status": f.status_vinculo or "",
            "foi_substituido": (f.foi_substituido or "").lower() == "sim",
            "observacoes": f.observacoes or "",
        })

        equipe["custo_total"] += valor
        equipe["qtd_membros"] += 1

        if (f.foi_substituido or "").lower() == "sim":
            equipe["teve_troca"] = True
            equipe["substituicoes"].append({
                "funcao": f.funcao_autonomo or "-",
                "saiu": getattr(f.autonomo, "nome_autonomo", "-"),
                "entrou": getattr(f.autonomo_substituto, "nome_autonomo", "-"),
                "data": f.data_troca,
                "motivo": getattr(f.motivo_troca, "motivo_troca", "-"),
                "justificativa": f.justificativa_troca or "",
            })

    equipes = list(equipes_map.values())

    return templates.TemplateResponse(
        "equipes/index.html",
        {
            "request": request,
            "equipes": equipes,
            "etapas": etapas,
            "categorias": categorias,
            "id_etapa": id_etapa,
            "id_prova": id_prova,
        },
    )
