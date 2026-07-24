"""Módulo Autônomo Sede — lançamento de custos de serviço prestado à sede."""

from __future__ import annotations

import io
from datetime import datetime
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db, engine
from app.models import DimAutonomo
from app.template_config import templates
from app.utils import redirect_with_message

router = APIRouter(tags=["autonomo_sede"])

MOTIVOS = [
    "Serviço de manutenção",
    "Serviço administrativo",
    "Consultoria",
    "Suporte técnico",
    "Serviço de logística",
    "Serviço de comunicação",
    "Produção de conteúdo",
    "Serviço de TI",
    "Outro",
]

# ─── migração automática ────────────────────────────────────────────
def _garantir_tabela():
    with engine.begin() as conn:
        dialect = conn.dialect.name
        if dialect == "sqlite":
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS autonomo_sede_lancamentos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    id_autonomo VARCHAR(40),
                    nome_autonomo VARCHAR(200),
                    motivo VARCHAR(200),
                    valor FLOAT DEFAULT 0,
                    competencia VARCHAR(20),
                    observacao TEXT,
                    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
        else:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS autonomo_sede_lancamentos (
                    id SERIAL PRIMARY KEY,
                    id_autonomo VARCHAR(40),
                    nome_autonomo VARCHAR(200),
                    motivo VARCHAR(200),
                    valor FLOAT DEFAULT 0,
                    competencia VARCHAR(20),
                    observacao TEXT,
                    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))

_garantir_tabela()


def _parse_valor(s: str) -> float:
    if not s:
        return 0.0
    s = s.strip().replace("R$", "").replace(" ", "")
    # aceita vírgula como decimal
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


# ─── listagem ────────────────────────────────────────────────────────
@router.get("/autonomo-sede")
def sede_index(request: Request, competencia: str = "", db: Session = Depends(get_db)):
    where = "WHERE 1=1"
    params: dict = {}
    if competencia:
        where += " AND competencia = :comp"
        params["comp"] = competencia

    lancamentos = db.execute(
        text(f"""
            SELECT id, id_autonomo, nome_autonomo, motivo, valor, competencia, observacao, criado_em
            FROM autonomo_sede_lancamentos
            {where}
            ORDER BY criado_em DESC
        """), params
    ).mappings().all()

    competencias = db.execute(
        text("SELECT DISTINCT competencia FROM autonomo_sede_lancamentos WHERE competencia IS NOT NULL ORDER BY competencia DESC")
    ).scalars().all()

    total = sum(float(r["valor"] or 0) for r in lancamentos)

    return templates.TemplateResponse("autonomo_sede/index.html", {
        "request": request,
        "lancamentos": lancamentos,
        "competencias": competencias,
        "filtro_competencia": competencia,
        "total": total,
        "motivos": MOTIVOS,
        **_flash(request),
    })


# ─── novo lançamento manual ──────────────────────────────────────────
@router.post("/autonomo-sede/novo")
def sede_novo(
    request: Request,
    id_autonomo: str = Form(""),
    nome_autonomo: str = Form(""),
    motivo: str = Form(""),
    valor: str = Form("0"),
    competencia: str = Form(""),
    observacao: str = Form(""),
    db: Session = Depends(get_db),
):
    db.execute(text("""
        INSERT INTO autonomo_sede_lancamentos (id_autonomo, nome_autonomo, motivo, valor, competencia, observacao)
        VALUES (:id_a, :nome, :motivo, :valor, :comp, :obs)
    """), {
        "id_a": id_autonomo.strip(),
        "nome": nome_autonomo.strip(),
        "motivo": motivo.strip(),
        "valor": _parse_valor(valor),
        "comp": competencia.strip(),
        "obs": observacao.strip(),
    })
    db.commit()
    return redirect_with_message("/autonomo-sede", success="Lançamento registrado.")


# ─── upload CSV/Excel ────────────────────────────────────────────────
@router.post("/autonomo-sede/upload")
async def sede_upload(
    request: Request,
    arquivo: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    nome = (arquivo.filename or "").lower()
    conteudo = await arquivo.read()
    linhas_ok = 0
    erros = 0

    try:
        if nome.endswith(".csv"):
            import csv
            reader = csv.DictReader(io.StringIO(conteudo.decode("utf-8-sig")))
            for row in reader:
                ok = _inserir_linha(db, row)
                if ok:
                    linhas_ok += 1
                else:
                    erros += 1

        elif nome.endswith(".xlsx") or nome.endswith(".xls"):
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(conteudo), data_only=True)
            ws = wb.active
            # detecta a linha de cabeçalho: primeira linha que contém "id" na coluna A
            header_row = 1
            for r in ws.iter_rows(min_row=1, max_row=10):
                val = str(r[0].value or "").strip().lower()
                if "id" in val:
                    header_row = r[0].row
                    break
            headers = [str(c.value or "").strip().lower() for c in ws[header_row]]
            for row in ws.iter_rows(min_row=header_row + 1, values_only=True):
                if all(v is None for v in row):
                    continue
                row_dict = {headers[i]: (str(v) if v is not None else "") for i, v in enumerate(row)}
                ok = _inserir_linha(db, row_dict)
                if ok:
                    linhas_ok += 1
                else:
                    erros += 1
        else:
            return redirect_with_message("/autonomo-sede", error="Formato não suportado. Use .csv ou .xlsx")

        db.commit()
        msg = f"{linhas_ok} lançamento(s) importado(s)."
        if erros:
            msg += f" {erros} linha(s) ignorada(s) (sem ID ou valor)."
        return redirect_with_message("/autonomo-sede", success=msg)

    except Exception as exc:
        return redirect_with_message("/autonomo-sede", error=f"Erro ao processar arquivo: {exc}")


def _inserir_linha(db: Session, row: dict) -> bool:
    """Normaliza os nomes das colunas e insere uma linha. Retorna True se inseriu."""
    def _get(*keys):
        for k in keys:
            for rk in row:
                if rk.lower().replace(" ", "_") == k.lower().replace(" ", "_"):
                    return str(row[rk]).strip()
            for rk in row:
                if k.lower() in rk.lower():
                    return str(row[rk]).strip()
        return ""

    id_a = _get("id_autonomo", "id", "código", "codigo")
    nome = _get("nome_autonomo", "nome")
    motivo = _get("motivo")
    valor_str = _get("valor")
    comp = _get("competencia", "competência")
    obs = _get("observacao", "observação")

    # normaliza competência: "2026-05-01 00:00:00" → "2026-05"
    if comp and len(comp) >= 7 and comp[4] == "-":
        comp = comp[:7]

    valor = _parse_valor(valor_str)
    if not id_a and not nome:
        return False

    db.execute(text("""
        INSERT INTO autonomo_sede_lancamentos (id_autonomo, nome_autonomo, motivo, valor, competencia, observacao)
        VALUES (:id_a, :nome, :motivo, :valor, :comp, :obs)
    """), {"id_a": id_a, "nome": nome, "motivo": motivo, "valor": valor, "comp": comp, "obs": obs})
    return True


# ─── modelo Excel ────────────────────────────────────────────────────
@router.get("/autonomo-sede/modelo")
def sede_modelo(db: Session = Depends(get_db)):
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

    autonomos = (
        db.query(DimAutonomo)
        .filter(DimAutonomo.status_autonomo == "Ativo")
        .order_by(DimAutonomo.nome_autonomo)
        .all()
    )

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Autônomo Sede"

    ws["A1"] = "Modelo — Autônomo Sede"
    ws["A1"].font = Font(bold=True, size=13)
    ws["A2"] = "Preencha: Motivo, Valor, Competência e Observação. Não altere ID e Nome."
    ws["A2"].font = Font(italic=True, color="888888", size=9)
    ws.merge_cells("A1:F1")
    ws.merge_cells("A2:F2")

    headers = ["ID Autônomo", "Nome", "Motivo", "Valor (R$)", "Competência", "Observação"]
    red = PatternFill("solid", fgColor="DC2626")
    hfont = Font(bold=True, color="FFFFFF", size=10)
    thin = Side(style="thin", color="D1D5DB")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=4, column=col, value=h)
        cell.fill = red
        cell.font = hfont
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border

    alt = PatternFill("solid", fgColor="F9FAFB")
    for i, a in enumerate(autonomos):
        row = 5 + i
        fill = alt if i % 2 == 0 else PatternFill("solid", fgColor="FFFFFF")
        for col, v in enumerate([a.id_autonomo, a.nome_autonomo, "", "", "", ""], 1):
            cell = ws.cell(row=row, column=col, value=v)
            cell.fill = fill
            cell.border = border
            cell.font = Font(size=9)
            if col == 1:
                cell.alignment = Alignment(horizontal="center")

    for col, w in enumerate([14, 40, 28, 16, 14, 40], 1):
        ws.column_dimensions[ws.cell(row=4, column=col).column_letter].width = w
    ws.freeze_panes = "A5"

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="modelo_autonomo_sede.xlsx"'},
    )


# ─── excluir ─────────────────────────────────────────────────────────
@router.post("/autonomo-sede/{id}/excluir")
def sede_excluir(id: int, request: Request, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM autonomo_sede_lancamentos WHERE id = :id"), {"id": id})
    db.commit()
    return redirect_with_message("/autonomo-sede", success="Lançamento excluído.")


def _flash(request: Request) -> dict:
    try:
        from app.utils import flash_from_request
        return flash_from_request(request)
    except Exception:
        return {}
