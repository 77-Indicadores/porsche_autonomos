
from __future__ import annotations

import io
import re
import sqlite3
from datetime import datetime, date
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi import APIRouter, UploadFile, File
from fastapi.responses import HTMLResponse, StreamingResponse

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

try:
    from app.logging_utils import log_error
except Exception:
    def log_error(contexto, exc, extra=None, excel=False):
        print(contexto, exc, extra)
        return "sem_log"


router = APIRouter(prefix="/excel", tags=["Excel"])

BASE_DIR = Path(__file__).resolve().parents[2]
DB_PATH = BASE_DIR / "data" / "app.db"


ENTIDADES = {
    "pilotos": {
        "label": "Pilotos",
        "table": "dim_pilotos",
        "unique": ["cpf"],
        "columns": [
            "nome_piloto", "cpf", "telefone", "email", "equipe",
            "categoria_atual", "data_inclusao", "data_desligamento",
            "motivo_desligamento", "status_piloto", "observacoes"
        ],
        "example": [
            "Rafael Martins", "111.111.111-11", "(11) 99999-1001",
            "rafael@email.com", "Equipe Alpha", "Carrera Cup",
            "2026-01-10", "", "", "Ativo", "Exemplo"
        ],
    },
    "autonomos": {
        "label": "Autônomos",
        "table": "dim_autonomos",
        "unique": ["cpf"],
        "columns": [
            "nome_autonomo", "cpf", "telefone", "email", "tipo_autonomo",
            "especialidade", "data_inclusao", "data_saida", "motivo_saida",
            "status_autonomo", "observacoes"
        ],
        "example": [
            "João Silva", "555.555.555-55", "(11) 98888-1001",
            "joao@email.com", "Mecânico", "Suspensão", "2026-01-05",
            "", "", "Ativo", "Exemplo"
        ],
    },
    "etapas": {
        "label": "Etapas",
        "table": "dim_etapas",
        "unique": ["temporada", "nome_etapa"],
        "columns": [
            "temporada", "nome_etapa", "local", "data_inicio",
            "data_fim", "status_etapa", "observacoes"
        ],
        "example": [
            "2026", "Etapa 01 - Interlagos", "São Paulo/SP",
            "2026-03-13", "2026-03-15", "Planejada", "Exemplo"
        ],
    },
    "tipos-prova": {
        "label": "Tipos de Prova",
        "table": "dim_tipos_prova",
        "unique": ["nome_tipo_prova"],
        "columns": ["nome_tipo_prova", "descricao", "status_tipo_prova"],
        "example": ["Sprint", "Prova curta", "Ativo"],
    },
    "provas": {
        "label": "Provas",
        "table": "dim_provas",
        "unique": ["id_etapa", "id_tipo_prova", "nome_prova"],
        "columns": [
            "id_etapa", "id_tipo_prova", "nome_prova",
            "data_prova", "status_prova", "observacoes"
        ],
        "example": ["1", "1", "Sprint - Interlagos", "2026-03-14", "Planejada", "Exemplo"],
    },
    "motivos-troca": {
        "label": "Motivos de Troca",
        "table": "dim_motivos_troca",
        "unique": ["motivo_troca"],
        "columns": ["motivo_troca", "descricao", "status"],
        "example": ["Solicitação do piloto", "Troca solicitada pelo piloto", "Ativo"],
    },
    "status-pagamento": {
        "label": "Status de Pagamento",
        "table": "dim_status_pagamento",
        "unique": ["status_pagamento"],
        "columns": ["status_pagamento"],
        "example": ["Pendente"],
    },
    "alocacoes": {
        "label": "Alocações / Fato Principal",
        "table": "fato_piloto_autonomo_prova",
        "unique": ["id_piloto", "id_autonomo", "id_etapa", "id_prova", "funcao_autonomo"],
        "columns": [
            "id_piloto", "id_autonomo", "id_etapa", "id_prova",
            "funcao_autonomo", "data_inicio_vinculo", "data_fim_vinculo",
            "status_vinculo", "foi_substituido", "id_autonomo_substituto",
            "data_troca", "id_motivo_troca", "justificativa_troca",
            "nota_tecnica", "nota_pontualidade", "nota_comunicacao",
            "nota_relacionamento", "nota_geral", "comentario_avaliacao",
            "data_avaliacao", "valor_fechado_etapa", "status_pagamento",
            "data_pagamento", "documento", "observacoes", "usuario_responsavel"
        ],
        "example": [
            "1", "1", "1", "1", "Mecânico", "2026-03-10", "",
            "Ativo", "Não", "", "", "", "", "8", "9", "8", "9",
            "8.5", "Boa avaliação", "2026-03-15", "3300",
            "Pendente", "", "NF-001", "Exemplo", "Felipe"
        ],
    },
}


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def norm_header(value: Any) -> str:
    value = str(value or "").strip().lower()
    value = value.replace(" ", "_").replace("-", "_")
    return re.sub(r"[^a-z0-9_áéíóúàãõâêôç]", "", value)


def normalize_value(value: Any) -> Any:
    if value is None:
        return None

    if isinstance(value, datetime):
        return value.date().isoformat()

    if isinstance(value, date):
        return value.isoformat()

    if isinstance(value, str):
        text = value.strip()

        if text == "":
            return None

        for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(text, fmt).date().isoformat()
            except Exception:
                pass

        money = text.replace("R$", "").replace(".", "").replace(",", ".").strip()

        if re.fullmatch(r"-?\d+(\.\d+)?", money) and any(x in text for x in ["R$", ","]):
            try:
                return float(Decimal(money))
            except Exception:
                return text

        return text

    return value


def table_exists(conn, table):
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def get_table_columns(conn, table):
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [r["name"] for r in rows]


def get_pk_column(conn, table):
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    for r in rows:
        if r["pk"] == 1:
            return r["name"]
    return None


def make_template(entity_key):
    cfg = ENTIDADES[entity_key]

    wb = Workbook()
    ws = wb.active
    sheet_title = str(cfg["label"])
    for invalid in [":", "\\", "/", "?", "*", "[", "]"]:
        sheet_title = sheet_title.replace(invalid, "-")
    sheet_title = sheet_title.strip() or "Planilha"
    ws.title = sheet_title[:31]

    ws.append(cfg["columns"])
    ws.append(cfg["example"])

    header_fill = PatternFill("solid", fgColor="111827")
    header_font = Font(color="FFFFFF", bold=True)

    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")

    for idx, col in enumerate(cfg["columns"], start=1):
        ws.column_dimensions[get_column_letter(idx)].width = max(18, len(col) + 3)

    ws.freeze_panes = "A2"

    leia = wb.create_sheet("LEIA-ME")
    leia["A1"] = "Instruções"
    leia["A1"].font = Font(bold=True, size=14)
    leia["A3"] = "Preencha a primeira aba mantendo os nomes das colunas."
    leia["A4"] = "Não renomeie nem exclua cabeçalhos."
    leia["A5"] = "Datas podem estar em DD/MM/AAAA ou AAAA-MM-DD."
    leia["A6"] = "O custo é valor_fechado_etapa. Não existe quantidade x valor unitário."
    leia.column_dimensions["A"].width = 100

    return wb


def workbook_stream(wb):
    stream = io.BytesIO()
    wb.save(stream)
    stream.seek(0)
    return stream


def read_rows_from_excel(file_bytes):
    wb = load_workbook(io.BytesIO(file_bytes), data_only=True)
    ws = wb[wb.sheetnames[0]]

    headers = [norm_header(c.value) for c in ws[1]]

    rows = []

    for row_idx in range(2, ws.max_row + 1):
        values = [
            ws.cell(row=row_idx, column=col_idx).value
            for col_idx in range(1, len(headers) + 1)
        ]

        if all(v is None or str(v).strip() == "" for v in values):
            continue

        row = {}

        for h, v in zip(headers, values):
            if h:
                row[h] = normalize_value(v)

        row["_linha_excel"] = row_idx
        rows.append(row)

    return headers, rows


def insert_or_update(conn, table, row, unique_keys):
    db_cols = get_table_columns(conn, table)
    pk = get_pk_column(conn, table)

    clean = {
        k: normalize_value(v)
        for k, v in row.items()
        if k in db_cols and k != pk and not k.startswith("_")
    }

    if not clean:
        return "ignorado"

    usable_keys = [k for k in unique_keys if k in clean and clean.get(k) not in [None, ""]]

    existing = None

    if usable_keys:
        where = " AND ".join([f"{k}=?" for k in usable_keys])
        vals = [clean[k] for k in usable_keys]
        existing = conn.execute(f"SELECT * FROM {table} WHERE {where} LIMIT 1", vals).fetchone()

    if existing:
        set_cols = [k for k in clean.keys() if k not in usable_keys]

        if set_cols:
            sql = f"UPDATE {table} SET " + ", ".join([f"{c}=?" for c in set_cols]) + f" WHERE {where}"
            conn.execute(sql, [clean[c] for c in set_cols] + vals)

        return "atualizado"

    cols = list(clean.keys())
    sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['?'] * len(cols))})"
    conn.execute(sql, [clean[c] for c in cols])

    return "criado"


@router.get("/", response_class=HTMLResponse)
def excel_home():
    cards = ""

    for key, cfg in ENTIDADES.items():
        cards += f"""
        <div class="card">
            <h3>{cfg["label"]}</h3>
            <p>Tabela: <code>{cfg["table"]}</code></p>
            <a class="btn primary" href="/excel/modelo/{key}">Baixar modelo Excel</a>
            <form action="/excel/importar/{key}" method="post" enctype="multipart/form-data">
                <input type="file" name="arquivo" accept=".xlsx" required>
                <button class="btn" type="submit">Importar Excel</button>
            </form>
        </div>
        """

    return HTMLResponse(f"""
    <!doctype html>
    <html lang="pt-br">
    <head>
        <meta charset="utf-8">
        <title>Importações Excel</title>
        <style>
            body {{ margin:0; font-family:Arial; background:#0f172a; color:#e5e7eb; }}
            .page {{ max-width:1200px; margin:0 auto; padding:32px; }}
            .top {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:22px; }}
            .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); gap:16px; }}
            .card {{ background:#111827; border:1px solid #1f2937; border-radius:18px; padding:20px; }}
            .btn {{ display:inline-block; border:0; border-radius:10px; padding:10px 14px; margin:8px 0; color:white; background:#374151; text-decoration:none; font-weight:700; cursor:pointer; }}
            .primary {{ background:#dc2626; }}
            input {{ display:block; margin:8px 0; color:#e5e7eb; }}
            code {{ color:#fca5a5; }}
            a {{ color:#fca5a5; }}
        </style>
    </head>
    <body>
        <div class="page">
            <div class="top">
                <div>
                    <h1>Importações e Modelos Excel</h1>
                    <p>Baixe os modelos, preencha e importe os cadastros ou a fato principal.</p>
                </div>
                <a href="/">Voltar</a>
            </div>
            <div class="grid">{cards}</div>
        </div>
    </body>
    </html>
    """)


@router.get("/modelo/{entity_key}")
def baixar_modelo(entity_key: str):
    if entity_key not in ENTIDADES:
        return HTMLResponse("Modelo não encontrado.", status_code=404)

    wb = make_template(entity_key)
    filename = f"modelo_{entity_key}.xlsx"

    return StreamingResponse(
        workbook_stream(wb),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/importar/{entity_key}", response_class=HTMLResponse)
async def importar_excel(entity_key: str, arquivo: UploadFile = File(...)):
    if entity_key not in ENTIDADES:
        return HTMLResponse("Importação não encontrada.", status_code=404)

    if not arquivo.filename.lower().endswith(".xlsx"):
        return HTMLResponse("Envie um arquivo .xlsx.", status_code=400)

    cfg = ENTIDADES[entity_key]
    content = await arquivo.read()

    try:
        headers, rows = read_rows_from_excel(content)
    except Exception as exc:
        error_id = log_error(
            "ERRO_AO_LER_EXCEL",
            exc,
            {"entity_key": entity_key, "arquivo": arquivo.filename},
            excel=True,
        )
        return HTMLResponse(
            f"<h1>Erro ao ler Excel</h1><p>ID: {error_id}</p><p>{exc}</p><p><a href='/logs/excel'>Ver log</a></p>",
            status_code=400,
        )

    criados = 0
    atualizados = 0
    ignorados = 0
    erros = []

    conn = get_conn()

    try:
        if not table_exists(conn, cfg["table"]):
            raise Exception(f"Tabela não encontrada: {cfg['table']}")

        for row in rows:
            linha = row.get("_linha_excel")

            try:
                status = insert_or_update(conn, cfg["table"], row, cfg["unique"])

                if status == "criado":
                    criados += 1
                elif status == "atualizado":
                    atualizados += 1
                else:
                    ignorados += 1

            except Exception as exc:
                error_id = log_error(
                    "ERRO_LINHA_IMPORTACAO_EXCEL",
                    exc,
                    {
                        "entity_key": entity_key,
                        "table": cfg["table"],
                        "arquivo": arquivo.filename,
                        "linha_excel": linha,
                        "row": row,
                    },
                    excel=True,
                )
                erros.append((linha, error_id, str(exc)))

        conn.commit()

    except Exception as exc:
        conn.rollback()
        error_id = log_error(
            "ERRO_IMPORTACAO_EXCEL",
            exc,
            {"entity_key": entity_key, "table": cfg["table"], "arquivo": arquivo.filename},
            excel=True,
        )
        return HTMLResponse(
            f"<h1>Erro na importação</h1><p>ID: {error_id}</p><p>{exc}</p><p><a href='/logs/excel'>Ver log</a></p>",
            status_code=400,
        )

    finally:
        conn.close()

    linhas_erro = "".join([f"<tr><td>{l}</td><td>{eid}</td><td>{e}</td></tr>" for l, eid, e in erros])

    return HTMLResponse(f"""
    <!doctype html>
    <html lang="pt-br">
    <head>
        <meta charset="utf-8">
        <title>Resultado Importação</title>
        <style>
            body {{ margin:0; font-family:Arial; background:#0f172a; color:#e5e7eb; }}
            .page {{ max-width:900px; margin:0 auto; padding:32px; }}
            .card {{ background:#111827; border:1px solid #1f2937; border-radius:18px; padding:22px; }}
            table {{ width:100%; border-collapse:collapse; margin-top:16px; }}
            th,td {{ border-bottom:1px solid #374151; padding:10px; text-align:left; }}
            a {{ color:#fca5a5; font-weight:700; }}
        </style>
    </head>
    <body>
        <div class="page">
            <div class="card">
                <h1>Resultado da Importação</h1>
                <p><b>Arquivo:</b> {arquivo.filename}</p>
                <p><b>Entidade:</b> {cfg["label"]}</p>
                <p>Linhas lidas: <b>{len(rows)}</b></p>
                <p>Criados: <b>{criados}</b> | Atualizados: <b>{atualizados}</b> | Ignorados: <b>{ignorados}</b> | Erros: <b>{len(erros)}</b></p>
                <p><a href="/excel/">Voltar para Excel</a> | <a href="/logs/excel">Ver log Excel</a></p>
                <table>
                    <thead><tr><th>Linha</th><th>ID Erro</th><th>Erro</th></tr></thead>
                    <tbody>{linhas_erro}</tbody>
                </table>
            </div>
        </div>
    </body>
    </html>
    """)
