import io
from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse, StreamingResponse
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
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

        # Autonomos que já estavam na etapa anterior por (piloto, carro, categoria, função)
        autonomos_na_ant: dict = {}
        for f in fatos_ant:
            chave = (f.id_piloto, f.id_carro, _nome_prova(f), f.funcao_autonomo or "")
            autonomos_na_ant.setdefault(chave, set()).add(f.id_autonomo)

        # Substituto 1-para-1: novo autonomo na mesma função do ausente
        substitutos_map: dict = {}
        for f in fatos_prox_list:
            chave = (f.id_piloto, f.id_carro, _nome_prova(f), f.funcao_autonomo or "")
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
                subs = substitutos_map.get((f.id_piloto, f.id_carro, nome, f.funcao_autonomo or ""), [])
                if not subs:
                    # Fallback: funcao_autonomo pode diferir entre etapas — ignora a função
                    for (pid, cid, pnome, _fn), names in substitutos_map.items():
                        if pid == f.id_piloto and cid == f.id_carro and pnome == nome:
                            subs = subs + names
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

        trocas_reais = [f for f in ausentes if f.id_fato not in ids_piloto_nao_correu]
        nao_correram = [f for f in ausentes if f.id_fato in ids_piloto_nao_correu]

        # Quebra por categoria (nome da prova) dentro do par de etapas
        por_categoria: dict = {}
        for f in trocas_reais:
            por_categoria.setdefault(_nome_prova(f) or "Sem categoria", []).append(f)
        trocas_por_categoria = sorted(por_categoria.items(), key=lambda kv: kv[0])

        grupos.append({
            "etapa_ant": ant,
            "etapa_prox": prox,
            "ausentes": ausentes,
            "trocas_salvas": trocas_salvas,
            "ids_piloto_nao_correu": ids_piloto_nao_correu,
            "substitutos": substitutos,
            "trocas_reais": trocas_reais,
            "nao_correram": nao_correram,
            "trocas_por_categoria": trocas_por_categoria,
        })

    return templates.TemplateResponse(
        "troca_etapas/index.html",
        {
            "request": request,
            "motivos": motivos,
            "grupos": grupos,
        },
    )


@router.get("/troca-etapas/exportar")
def exportar_excel(db: Session = Depends(get_db)):
    etapas = db.query(DimEtapa).order_by(
        DimEtapa.temporada.desc(),
        DimEtapa.data_inicio,
        DimEtapa.nome_etapa,
    ).all()

    motivos_map = {
        m.id_motivo_troca: m.motivo_troca
        for m in db.query(DimMotivoTroca).all()
    }

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

    todas_trocas = db.execute(select(troca_entre_etapas)).mappings().all()
    trocas_db: dict = {}
    for t in todas_trocas:
        key = (t["id_etapa_anterior"], t["id_etapa_proxima"], t["id_fato"])
        trocas_db[key] = dict(t)

    wb = Workbook()
    ws = wb.active
    ws.title = "Troca de Etapas"

    header_fill = PatternFill("solid", fgColor="1E293B")
    header_font = Font(bold=True, color="F1F5F9", size=11)
    header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)

    headers = [
        "Temporada", "Etapa Anterior", "Etapa Seguinte",
        "Tipo", "Piloto", "Carro / Chassi", "Categoria",
        "Autônomo", "Função", "Substituto (etapa seguinte)",
        "Motivo de Troca", "Justificativa", "Status",
    ]
    col_widths = [12, 28, 28, 22, 28, 16, 18, 32, 20, 32, 28, 32, 14]

    for col_idx, (h, w) in enumerate(zip(headers, col_widths), start=1):
        cell = ws.cell(row=1, column=col_idx, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align
        ws.column_dimensions[cell.column_letter].width = w

    ws.row_dimensions[1].height = 30

    def _nome_prova(f):
        return (f.prova.nome_prova if f.prova else None) or ""

    row_num = 2
    for i in range(len(etapas) - 1):
        ant = etapas[i]
        prox = etapas[i + 1]
        if ant.temporada != prox.temporada:
            continue

        fatos_ant = fatos_por_etapa.get(ant.id_etapa, [])
        fatos_prox_list = fatos_por_etapa.get(prox.id_etapa, [])

        nomes_na_prox = {_nome_prova(f) for f in fatos_prox_list}
        chaves_prox = {(f.id_autonomo, f.id_piloto, f.id_carro, _nome_prova(f)) for f in fatos_prox_list}
        pilotos_na_prox = {(f.id_piloto, _nome_prova(f)) for f in fatos_prox_list}

        autonomos_na_ant: dict = {}
        for f in fatos_ant:
            chave = (f.id_piloto, f.id_carro, _nome_prova(f), f.funcao_autonomo or "")
            autonomos_na_ant.setdefault(chave, set()).add(f.id_autonomo)

        substitutos_map: dict = {}
        for f in fatos_prox_list:
            chave = (f.id_piloto, f.id_carro, _nome_prova(f), f.funcao_autonomo or "")
            ja_estava = autonomos_na_ant.get(chave, set())
            if f.id_autonomo not in ja_estava:
                nome_aut = getattr(f.autonomo, "nome_autonomo", None) or "—"
                substitutos_map.setdefault(chave, []).append(nome_aut)

        for f in fatos_ant:
            nome = _nome_prova(f)
            if nome not in nomes_na_prox:
                continue
            if (f.id_autonomo, f.id_piloto, f.id_carro, nome) in chaves_prox:
                continue

            nao_correu = (f.id_piloto, nome) not in pilotos_na_prox
            tipo = "Piloto não correu" if nao_correu else "Troca de autônomo"

            subs_chave = (f.id_piloto, f.id_carro, nome, f.funcao_autonomo or "")
            substitutos = ", ".join(substitutos_map.get(subs_chave, [])) or "—"

            key = (ant.id_etapa, prox.id_etapa, f.id_fato)
            troca = trocas_db.get(key)
            motivo_label = motivos_map.get(troca["id_motivo_troca"], "") if troca and troca.get("id_motivo_troca") else ""
            justificativa = (troca.get("justificativa") or "") if troca else ""
            status = "Justificado" if troca else "Não justificado"

            ws.append([
                ant.temporada,
                ant.nome_etapa,
                prox.nome_etapa,
                tipo,
                getattr(f.piloto, "nome_piloto", "") or "",
                getattr(f.carro, "chassi", "") or str(f.id_carro or ""),
                nome,
                getattr(f.autonomo, "nome_autonomo", "") or "",
                f.funcao_autonomo or "",
                substitutos,
                motivo_label,
                justificativa,
                status,
            ])

            if nao_correu:
                for col in range(1, len(headers) + 1):
                    ws.cell(row=row_num, column=col).fill = PatternFill("solid", fgColor="1E3A5F")

            row_num += 1

    ws.freeze_panes = "A2"

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    filename = f"troca_etapas_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/troca-etapas/registrar")
def registrar_motivo(
    request: Request,
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
    if request.headers.get("x-fetch") == "1":
        return JSONResponse({"ok": True})
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
