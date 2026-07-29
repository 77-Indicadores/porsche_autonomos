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
    text,
    update,
)
from sqlalchemy.orm import Session, joinedload

from app.database import engine, get_db
from app.models import DimAutonomo, DimEtapa, DimMotivoTroca, FatoPilotoAutonomoProva
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
    Column("id_autonomo_substituto", Integer, nullable=True),
    Column("justificativa", Text, nullable=True),
    Column("registrado_em", DateTime, default=datetime.utcnow),
    UniqueConstraint("id_etapa_anterior", "id_etapa_proxima", "id_fato", name="uq_troca_etapas_fato"),
)

_metadata.create_all(engine)


def _garantir_schema():
    try:
        with engine.begin() as conn:
            if conn.dialect.name == "postgresql":
                conn.execute(text("""
                    ALTER TABLE IF EXISTS troca_entre_etapas
                    ADD COLUMN IF NOT EXISTS id_autonomo_substituto INTEGER
                """))
    except Exception as exc:
        print(f"AVISO - troca_entre_etapas schema: {exc}")


_garantir_schema()


@router.get("/troca-etapas")
def troca_etapas_index(request: Request, db: Session = Depends(get_db)):
    etapas = db.query(DimEtapa).order_by(
        DimEtapa.temporada.desc(),
        DimEtapa.data_inicio,
        DimEtapa.nome_etapa,
    ).all()

    motivos = (
        db.query(DimMotivoTroca)
        .filter(DimMotivoTroca.status == "Ativo")
        .order_by(DimMotivoTroca.motivo_troca)
        .all()
    )
    motivos_map = {m.id_motivo_troca: m.motivo_troca for m in motivos}

    autonomos_map = {
        a.id_autonomo: a.nome_autonomo
        for a in db.query(DimAutonomo).all()
    }

    # Todos os fatos carregados de uma vez
    todos_fatos = (
        db.query(FatoPilotoAutonomoProva)
        .options(
            joinedload(FatoPilotoAutonomoProva.piloto),
            joinedload(FatoPilotoAutonomoProva.autonomo),
            joinedload(FatoPilotoAutonomoProva.prova),
            joinedload(FatoPilotoAutonomoProva.carro),
        )
        .all()
    )
    fatos_por_etapa: dict = {}
    for f in todos_fatos:
        fatos_por_etapa.setdefault(f.id_etapa, []).append(f)

    # Todos os registros de troca já salvos
    todas_trocas = db.execute(select(troca_entre_etapas)).mappings().all()
    trocas_db: dict = {}
    for t in todas_trocas:
        key = (t["id_etapa_anterior"], t["id_etapa_proxima"], t["id_fato"])
        trocas_db[key] = dict(t)

    # Grupos: um por par consecutivo dentro da mesma temporada
    grupos = []
    for i in range(len(etapas) - 1):
        ant = etapas[i]
        prox = etapas[i + 1]

        if ant.temporada != prox.temporada:
            continue

        fatos_ant = fatos_por_etapa.get(ant.id_etapa, [])
        fatos_prox_list = fatos_por_etapa.get(prox.id_etapa, [])

        def _nome_prova(f):
            return (f.prova.nome_prova if f.prova else None) or ""

        nomes_na_prox = {_nome_prova(f) for f in fatos_prox_list}
        chaves_prox = {
            (f.id_autonomo, f.id_piloto, f.id_carro, _nome_prova(f))
            for f in fatos_prox_list
        }
        pilotos_na_prox = {(f.id_piloto, _nome_prova(f)) for f in fatos_prox_list}

        # Autonomos que já estavam na etapa anterior por (piloto, carro, categoria)
        autonomos_na_ant: dict = {}
        for f in fatos_ant:
            chave = (f.id_piloto, f.id_carro, _nome_prova(f))
            autonomos_na_ant.setdefault(chave, set()).add(f.id_autonomo)

        # Substituto = quem está na etapa seguinte para o mesmo combo e NÃO estava antes
        substitutos_map: dict = {}
        for f in fatos_prox_list:
            chave = (f.id_piloto, f.id_carro, _nome_prova(f))
            ja_estava = autonomos_na_ant.get(chave, set())
            if f.id_autonomo not in ja_estava:
                nome_aut = getattr(f.autonomo, "nome_autonomo", None) or "—"
                substitutos_map.setdefault(chave, []).append(nome_aut)

        ausentes = []
        ids_piloto_nao_correu = set()
        substitutos: dict = {}  # id_fato → lista de nomes substitutos
        for f in fatos_ant:
            nome = _nome_prova(f)
            if nome not in nomes_na_prox:
                continue
            if (f.id_autonomo, f.id_piloto, f.id_carro, nome) in chaves_prox:
                continue
            ausentes.append(f)
            if (f.id_piloto, nome) not in pilotos_na_prox:
                ids_piloto_nao_correu.add(f.id_fato)
            else:
                subs = substitutos_map.get((f.id_piloto, f.id_carro, nome), [])
                if subs:
                    substitutos[f.id_fato] = subs

        trocas_salvas: dict = {}
        for f in ausentes:
            key = (ant.id_etapa, prox.id_etapa, f.id_fato)
            if key in trocas_db:
                t = trocas_db[key]
                trocas_salvas[f.id_fato] = {
                    "id_motivo_troca": t["id_motivo_troca"],
                    "justificativa": t["justificativa"] or "",
                    "motivo_label": motivos_map.get(t["id_motivo_troca"], ""),
                }

        grupos.append({
            "etapa_ant": ant,
            "etapa_prox": prox,
            "ausentes": ausentes,
            "trocas_salvas": trocas_salvas,
            "ids_piloto_nao_correu": ids_piloto_nao_correu,
            "substitutos": substitutos,
        })

    return templates.TemplateResponse(
        "troca_etapas/index.html",
        {
            "request": request,
            "motivos": motivos,
            "grupos": grupos,
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
    return redirect_with_message("/troca-etapas", success="Registrado com sucesso.")


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
    return redirect_with_message("/troca-etapas", success="Registro removido.")
