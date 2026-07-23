"""Planejamento de equipe por etapa — modelo Excel + upload de carga."""

from __future__ import annotations

import io
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db, engine
from app.models import DimAutonomo, DimEtapa
from app.template_config import templates
from app.utils import redirect_with_message

router = APIRouter(tags=["composicao_meta_equipe"])


# ─── migração automática ─────────────────────────────────────────────
def _garantir_tabela():
    with engine.begin() as conn:
        dialect = conn.dialect.name
        if dialect == "sqlite":
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS planejamento_equipe_etapa (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    id_etapa INTEGER,
                    id_autonomo INTEGER,
                    nome_autonomo VARCHAR(200),
                    cargo VARCHAR(200),
                    valor FLOAT DEFAULT 0,
                    observacao TEXT,
                    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
        else:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS planejamento_equipe_etapa (
                    id SERIAL PRIMARY KEY,
                    id_etapa INTEGER,
                    id_autonomo INTEGER,
                    nome_autonomo VARCHAR(200),
                    cargo VARCHAR(200),
                    valor FLOAT DEFAULT 0,
                    observacao TEXT,
                    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))

_garantir_tabela()


# ─── página principal ─────────────────────────────────────────────────
@router.get("/composicao-meta-equipe")
def index(request: Request, db: Session = Depends(get_db)):
    etapas = (
        db.query(DimEtapa)
        .order_by(DimEtapa.temporada.desc(), DimEtapa.data_inicio.asc())
        .all()
    )

    # quais etapas já têm planejamento carregado
    rows_com_plano = db.execute(
        text("SELECT DISTINCT id_etapa, COUNT(*) as qtd FROM planejamento_equipe_etapa GROUP BY id_etapa")
    ).mappings().all()
    etapas_com_plano = {r["id_etapa"]: r["qtd"] for r in rows_com_plano}

    return templates.TemplateResponse("composicao_meta_equipe/index.html", {
        "request": request,
        "etapas": etapas,
        "etapas_com_plano": etapas_com_plano,
        **_flash(request),
    })


# ─── detalhe de uma etapa ─────────────────────────────────────────────
@router.get("/composicao-meta-equipe/{id_etapa}")
def detalhe(id_etapa: int, request: Request, db: Session = Depends(get_db)):
    etapa = db.get(DimEtapa, id_etapa)
    if not etapa:
        return redirect_with_message("/composicao-meta-equipe", error="Etapa não encontrada.")

    linhas = db.execute(
        text("""
            SELECT id, id_autonomo, nome_autonomo, cargo, valor, observacao, criado_em
            FROM planejamento_equipe_etapa
            WHERE id_etapa = :eid
            ORDER BY nome_autonomo
        """), {"eid": id_etapa}
    ).mappings().all()

    total = sum(float(r["valor"] or 0) for r in linhas)

    return templates.TemplateResponse("composicao_meta_equipe/detalhe.html", {
        "request": request,
        "etapa": etapa,
        "linhas": linhas,
        "total": total,
        **_flash(request),
    })


# ─── exportar modelo Excel ────────────────────────────────────────────
@router.get("/composicao-meta-equipe/{id_etapa}/modelo")
def exportar_modelo(id_etapa: int, db: Session = Depends(get_db)):
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

    etapa = db.get(DimEtapa, id_etapa)
    nome_etapa = etapa.nome_etapa if etapa else f"Etapa {id_etapa}"

    autonomos = (
        db.query(DimAutonomo)
        .filter(DimAutonomo.status_autonomo == "Ativo")
        .order_by(DimAutonomo.nome_autonomo)
        .all()
    )

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Planejamento"

    # instrução no topo
    ws["A1"] = f"Planejamento de Equipe — {nome_etapa}"
    ws["A1"].font = Font(bold=True, size=13)
    ws["A2"] = "Preencha: Valor e Observação. Não altere as colunas ID e Nome. Salve e importe."
    ws["A2"].font = Font(italic=True, color="888888", size=9)
    ws.merge_cells("A1:F1")
    ws.merge_cells("A2:F2")

    # cabeçalho
    headers = ["ID Autônomo", "Nome", "Cargo", "Valor (R$)", "Observação"]
    header_fill = PatternFill("solid", fgColor="DC2626")
    header_font = Font(bold=True, color="FFFFFF", size=10)
    thin = Side(style="thin", color="D1D5DB")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=4, column=col, value=h)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border

    # autônomos ativos pré-preenchidos
    alt_fill = PatternFill("solid", fgColor="F9FAFB")
    for i, a in enumerate(autonomos):
        row = 5 + i
        fill = alt_fill if i % 2 == 0 else PatternFill("solid", fgColor="FFFFFF")
        values = [
            a.id_autonomo,
            a.nome_autonomo,
            a.especialidade or "",
            "",   # Valor — usuário preenche
            "",   # Observação — usuário preenche
        ]
        for col, v in enumerate(values, 1):
            cell = ws.cell(row=row, column=col, value=v)
            cell.fill = fill
            cell.border = border
            cell.font = Font(size=9)
            if col == 1:
                cell.alignment = Alignment(horizontal="center")

    # larguras
    widths = [14, 40, 28, 16, 40]
    for col, w in enumerate(widths, 1):
        ws.column_dimensions[ws.cell(row=4, column=col).column_letter].width = w

    # linha de instruções bloqueada ao topo
    ws.freeze_panes = "A5"

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    safe = nome_etapa.replace(" ", "_").replace("/", "-")
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="planejamento_{safe}.xlsx"'},
    )


# ─── upload / carga ───────────────────────────────────────────────────
@router.post("/composicao-meta-equipe/{id_etapa}/upload")
async def upload_planejamento(
    id_etapa: int,
    arquivo: UploadFile = File(...),
    substituir: str = Form("nao"),
    db: Session = Depends(get_db),
):
    import openpyxl

    conteudo = await arquivo.read()
    try:
        wb = openpyxl.load_workbook(io.BytesIO(conteudo), data_only=True)
        ws = wb.active
    except Exception as exc:
        return redirect_with_message(
            f"/composicao-meta-equipe/{id_etapa}", error=f"Erro ao ler arquivo: {exc}"
        )

    # detecta cabeçalho (linha com "ID Autônomo")
    header_row = None
    for row in ws.iter_rows(min_row=1, max_row=10):
        for cell in row:
            if str(cell.value or "").strip().lower() in ("id autônomo", "id autonomo", "id_autonomo"):
                header_row = cell.row
                break
        if header_row:
            break

    if not header_row:
        return redirect_with_message(
            f"/composicao-meta-equipe/{id_etapa}", error="Cabeçalho não encontrado. Use o modelo exportado."
        )

    headers = [str(ws.cell(row=header_row, column=c).value or "").strip().lower()
               for c in range(1, ws.max_column + 1)]

    def col(name):
        for alt in [name, name.replace(" ", "_"), name.replace("ã", "a").replace("ç", "c")]:
            for i, h in enumerate(headers):
                if alt in h:
                    return i + 1
        return None

    c_id = col("id")
    c_nome = col("nome")
    c_cargo = col("cargo")
    c_valor = col("valor")
    c_obs = col("observa")

    if substituir == "sim":
        db.execute(text("DELETE FROM planejamento_equipe_etapa WHERE id_etapa = :eid"), {"eid": id_etapa})

    ok = 0
    skip = 0
    for row in ws.iter_rows(min_row=header_row + 1, values_only=True):
        id_a = row[c_id - 1] if c_id else None
        nome = str(row[c_nome - 1] or "").strip() if c_nome else ""
        cargo = str(row[c_cargo - 1] or "").strip() if c_cargo else ""
        valor_raw = row[c_valor - 1] if c_valor else None
        obs = str(row[c_obs - 1] or "").strip() if c_obs else ""

        if not id_a and not nome:
            skip += 1
            continue

        valor = _parse_valor(str(valor_raw or "0"))

        db.execute(text("""
            INSERT INTO planejamento_equipe_etapa
                (id_etapa, id_autonomo, nome_autonomo, cargo, valor, observacao, criado_em, atualizado_em)
            VALUES (:eid, :id_a, :nome, :cargo, :valor, :obs, :now, :now)
        """), {
            "eid": id_etapa,
            "id_a": int(id_a) if id_a else None,
            "nome": nome,
            "cargo": cargo,
            "valor": valor,
            "obs": obs,
            "now": datetime.utcnow(),
        })
        ok += 1

    db.commit()
    msg = f"{ok} autônomo(s) importado(s) para o planejamento."
    if skip:
        msg += f" {skip} linha(s) em branco ignorada(s)."
    return redirect_with_message(f"/composicao-meta-equipe/{id_etapa}", success=msg)


# ─── excluir linha individual ─────────────────────────────────────────
@router.post("/composicao-meta-equipe/linha/{linha_id}/excluir")
def excluir_linha(linha_id: int, id_etapa: int = Form(...), db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM planejamento_equipe_etapa WHERE id = :id"), {"id": linha_id})
    db.commit()
    return redirect_with_message(f"/composicao-meta-equipe/{id_etapa}", success="Linha removida.")


# ─── limpar planejamento de etapa ─────────────────────────────────────
@router.post("/composicao-meta-equipe/{id_etapa}/limpar")
def limpar_planejamento(id_etapa: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM planejamento_equipe_etapa WHERE id_etapa = :eid"), {"eid": id_etapa})
    db.commit()
    return redirect_with_message(f"/composicao-meta-equipe/{id_etapa}", success="Planejamento limpo.")


def _parse_valor(s: str) -> float:
    s = s.strip().replace("R$", "").replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _flash(request: Request) -> dict:
    try:
        from app.utils import flash_from_request
        return flash_from_request(request)
    except Exception:
        return {}
