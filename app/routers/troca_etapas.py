from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    Table,
    Text,
    UniqueConstraint,
    delete,
    insert,
    select,
    update,
)
from sqlalchemy.orm import Session, joinedload

from app.database import engine, get_db
from app.models import DimEtapa, DimMotivoTroca, FatoPilotoAutonomoProva
from app.template_config import templates
from app.utils import redirect_with_message

router = APIRouter(tags=["troca_etapas"])

_metadata = MetaData()

troca_entre_etapas = Table(
    "troca_entre_etapas",
    _metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("id_etapa_anterior", Integer, nullable=False),
    Column("id_etapa_proxima", Integer, nullable=False),
    Column("id_fato", Integer, nullable=False),
    Column("id_motivo_troca", Integer, nullable=True),
    Column("justificativa", Text, nullable=True),
    Column("registrado_em", DateTime, default=datetime.utcnow),
    UniqueConstraint("id_etapa_anterior", "id_etapa_proxima", "id_fato", name="uq_troca_etapas_fato"),
)

_metadata.create_all(engine)


def _etapas_ordenadas(db: Session):
    """Retorna etapas ordenadas por data_inicio (nulls last), depois nome_etapa."""
    etapas = db.query(DimEtapa).order_by(
        DimEtapa.temporada.desc(),
        DimEtapa.data_inicio,
        DimEtapa.nome_etapa,
    ).all()
    return etapas


@router.get("/troca-etapas")
def troca_etapas_index(
    request: Request,
    etapa_ant: str = "",
    etapa_prox: str = "",
    db: Session = Depends(get_db),
):
    etapas = _etapas_ordenadas(db)
    motivos = db.query(DimMotivoTroca).filter(DimMotivoTroca.status == "Ativo").order_by(DimMotivoTroca.motivo_troca).all()

    id_ant = int(etapa_ant) if etapa_ant.strip() else None
    id_prox = int(etapa_prox) if etapa_prox.strip() else None

    ausentes = []
    trocas_salvas = {}
    etapa_ant_obj = None
    etapa_prox_obj = None

    if id_ant and id_prox and id_ant != id_prox:
        etapa_ant_obj = db.query(DimEtapa).get(id_ant)
        etapa_prox_obj = db.query(DimEtapa).get(id_prox)

        # Fatos da etapa anterior com todos os relacionamentos
        fatos_ant = (
            db.query(FatoPilotoAutonomoProva)
            .options(
                joinedload(FatoPilotoAutonomoProva.piloto),
                joinedload(FatoPilotoAutonomoProva.autonomo),
                joinedload(FatoPilotoAutonomoProva.prova),
                joinedload(FatoPilotoAutonomoProva.carro),
            )
            .filter(FatoPilotoAutonomoProva.id_etapa == id_ant)
            .all()
        )

        # Chaves (autonomo, piloto, carro) presentes na etapa seguinte
        fatos_prox = (
            db.query(
                FatoPilotoAutonomoProva.id_autonomo,
                FatoPilotoAutonomoProva.id_piloto,
                FatoPilotoAutonomoProva.id_carro,
            )
            .filter(FatoPilotoAutonomoProva.id_etapa == id_prox)
            .all()
        )
        chaves_prox = {(r.id_autonomo, r.id_piloto, r.id_carro) for r in fatos_prox}

        # Quem estava na anterior mas não aparece na seguinte
        ausentes = [
            f for f in fatos_ant
            if (f.id_autonomo, f.id_piloto, f.id_carro) not in chaves_prox
        ]

        # Motivos já registrados para este par de etapas
        if ausentes:
            ids_fatos = [f.id_fato for f in ausentes]
            rows = db.execute(
                select(troca_entre_etapas).where(
                    troca_entre_etapas.c.id_etapa_anterior == id_ant,
                    troca_entre_etapas.c.id_etapa_proxima == id_prox,
                    troca_entre_etapas.c.id_fato.in_(ids_fatos),
                )
            ).mappings().all()

            motivos_map = {m.id_motivo_troca: m.motivo_troca for m in motivos}
            for r in rows:
                trocas_salvas[r["id_fato"]] = {
                    "id_motivo_troca": r["id_motivo_troca"],
                    "justificativa": r["justificativa"] or "",
                    "motivo_label": motivos_map.get(r["id_motivo_troca"], ""),
                }

    return templates.TemplateResponse(
        "troca_etapas/index.html",
        {
            "request": request,
            "etapas": etapas,
            "motivos": motivos,
            "etapa_ant": id_ant,
            "etapa_prox": id_prox,
            "etapa_ant_obj": etapa_ant_obj,
            "etapa_prox_obj": etapa_prox_obj,
            "ausentes": ausentes,
            "trocas_salvas": trocas_salvas,
        },
    )


@router.post("/troca-etapas/registrar")
def registrar_motivo(
    id_etapa_anterior: int = Form(...),
    id_etapa_proxima: int = Form(...),
    id_fato: int = Form(...),
    id_motivo_troca: str = Form(""),
    justificativa: str = Form(""),
    db: Session = Depends(get_db),
):
    motivo_int = int(id_motivo_troca) if id_motivo_troca.strip() else None
    justificativa = justificativa.strip()

    existing = db.execute(
        select(troca_entre_etapas).where(
            troca_entre_etapas.c.id_etapa_anterior == id_etapa_anterior,
            troca_entre_etapas.c.id_etapa_proxima == id_etapa_proxima,
            troca_entre_etapas.c.id_fato == id_fato,
        )
    ).first()

    if existing:
        db.execute(
            update(troca_entre_etapas)
            .where(
                troca_entre_etapas.c.id_etapa_anterior == id_etapa_anterior,
                troca_entre_etapas.c.id_etapa_proxima == id_etapa_proxima,
                troca_entre_etapas.c.id_fato == id_fato,
            )
            .values(
                id_motivo_troca=motivo_int,
                justificativa=justificativa,
                registrado_em=datetime.utcnow(),
            )
        )
    else:
        db.execute(
            insert(troca_entre_etapas).values(
                id_etapa_anterior=id_etapa_anterior,
                id_etapa_proxima=id_etapa_proxima,
                id_fato=id_fato,
                id_motivo_troca=motivo_int,
                justificativa=justificativa,
                registrado_em=datetime.utcnow(),
            )
        )

    db.commit()

    return redirect_with_message(
        f"/troca-etapas?etapa_ant={id_etapa_anterior}&etapa_prox={id_etapa_proxima}",
        success="Motivo registrado com sucesso.",
    )


@router.post("/troca-etapas/excluir")
def excluir_motivo(
    id_etapa_anterior: int = Form(...),
    id_etapa_proxima: int = Form(...),
    id_fato: int = Form(...),
    db: Session = Depends(get_db),
):
    db.execute(
        delete(troca_entre_etapas).where(
            troca_entre_etapas.c.id_etapa_anterior == id_etapa_anterior,
            troca_entre_etapas.c.id_etapa_proxima == id_etapa_proxima,
            troca_entre_etapas.c.id_fato == id_fato,
        )
    )
    db.commit()

    return redirect_with_message(
        f"/troca-etapas?etapa_ant={id_etapa_anterior}&etapa_prox={id_etapa_proxima}",
        success="Registro removido.",
    )
