from pathlib import Path
import re

BASE = Path(__file__).resolve().parent

# ============================================================
# 1. Criar módulo de logging detalhado
# ============================================================

logging_utils = r'''
from __future__ import annotations

import json
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[1]
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

ERROR_LOG = LOG_DIR / "erros_detalhados.log"
EXCEL_LOG = LOG_DIR / "excel_import_errors.log"


def _safe_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, indent=2, default=str)
    except Exception:
        return str(value)


def log_error(contexto: str, exc: Exception, extra: dict | None = None, excel: bool = False) -> str:
    """
    Grava erro detalhado em arquivo .log.
    Retorna o id do erro para exibir na tela.
    """
    error_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")

    payload = {
        "error_id": error_id,
        "data_hora": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "contexto": contexto,
        "tipo_erro": type(exc).__name__,
        "mensagem": str(exc),
        "extra": extra or {},
        "traceback": traceback.format_exc(),
    }

    bloco = "\n" + "=" * 120 + "\n"
    bloco += _safe_json(payload)
    bloco += "\n" + "=" * 120 + "\n"

    ERROR_LOG.write_text(
        ERROR_LOG.read_text(encoding="utf-8") + bloco if ERROR_LOG.exists() else bloco,
        encoding="utf-8",
    )

    if excel:
        EXCEL_LOG.write_text(
            EXCEL_LOG.read_text(encoding="utf-8") + bloco if EXCEL_LOG.exists() else bloco,
            encoding="utf-8",
        )

    return error_id


def tail_log(path: Path, max_lines: int = 500) -> str:
    if not path.exists():
        return "Nenhum log encontrado ainda."

    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[-max_lines:])
'''

logging_path = BASE / "app" / "logging_utils.py"
logging_path.write_text(logging_utils, encoding="utf-8")
print("OK app/logging_utils.py criado")


# ============================================================
# 2. Criar router para visualizar logs no navegador
# ============================================================

logs_router = r'''
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, FileResponse

from app.logging_utils import LOG_DIR, ERROR_LOG, EXCEL_LOG, tail_log

router = APIRouter(prefix="/logs", tags=["Logs"])


def render_log_page(titulo: str, conteudo: str) -> HTMLResponse:
    html = f"""
    <!doctype html>
    <html lang="pt-br">
    <head>
        <meta charset="utf-8">
        <title>{titulo}</title>
        <style>
            body {{
                margin: 0;
                background: #0f172a;
                color: #e5e7eb;
                font-family: Arial, sans-serif;
            }}
            .page {{
                max-width: 1200px;
                margin: 0 auto;
                padding: 28px;
            }}
            h1 {{
                margin-top: 0;
            }}
            .actions {{
                display: flex;
                gap: 12px;
                margin-bottom: 16px;
                flex-wrap: wrap;
            }}
            a {{
                color: white;
                background: #dc2626;
                padding: 10px 14px;
                border-radius: 10px;
                text-decoration: none;
                font-weight: 700;
            }}
            pre {{
                background: #020617;
                border: 1px solid #1f2937;
                border-radius: 16px;
                padding: 18px;
                overflow: auto;
                white-space: pre-wrap;
                line-height: 1.45;
            }}
        </style>
    </head>
    <body>
        <div class="page">
            <h1>{titulo}</h1>
            <div class="actions">
                <a href="/">Voltar ao sistema</a>
                <a href="/excel/">Importações Excel</a>
                <a href="/logs/download/excel">Baixar log Excel</a>
                <a href="/logs/download/geral">Baixar log geral</a>
            </div>
            <pre>{conteudo}</pre>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(html)


@router.get("/", response_class=HTMLResponse)
def logs_home():
    html = """
    <!doctype html>
    <html lang="pt-br">
    <head>
        <meta charset="utf-8">
        <title>Logs do Sistema</title>
        <style>
            body { margin: 0; background: #0f172a; color: #e5e7eb; font-family: Arial, sans-serif; }
            .page { max-width: 900px; margin: 0 auto; padding: 32px; }
            .card { background: #111827; border: 1px solid #1f2937; border-radius: 18px; padding: 22px; margin-bottom: 16px; }
            a { color: white; background: #dc2626; padding: 10px 14px; border-radius: 10px; text-decoration: none; font-weight: 700; display: inline-block; margin-right: 10px; margin-top: 10px; }
        </style>
    </head>
    <body>
        <div class="page">
            <h1>Logs do Sistema</h1>
            <div class="card">
                <h2>Erros de Importação Excel</h2>
                <p>Use este log para corrigir erros de modelo, coluna, banco ou validação.</p>
                <a href="/logs/excel">Ver log Excel</a>
                <a href="/logs/download/excel">Baixar log Excel</a>
            </div>
            <div class="card">
                <h2>Erros Gerais</h2>
                <p>Erros 500, exceções não tratadas e falhas gerais do sistema.</p>
                <a href="/logs/geral">Ver log geral</a>
                <a href="/logs/download/geral">Baixar log geral</a>
            </div>
            <a href="/">Voltar ao sistema</a>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(html)


@router.get("/excel", response_class=HTMLResponse)
def ver_log_excel():
    return render_log_page("Log de Erros Excel", tail_log(EXCEL_LOG, 700))


@router.get("/geral", response_class=HTMLResponse)
def ver_log_geral():
    return render_log_page("Log de Erros Gerais", tail_log(ERROR_LOG, 700))


@router.get("/download/excel")
def download_excel_log():
    EXCEL_LOG.touch(exist_ok=True)
    return FileResponse(EXCEL_LOG, filename="excel_import_errors.log")


@router.get("/download/geral")
def download_geral_log():
    ERROR_LOG.touch(exist_ok=True)
    return FileResponse(ERROR_LOG, filename="erros_detalhados.log")
'''

logs_router_path = BASE / "app" / "routers" / "logs.py"
logs_router_path.write_text(logs_router, encoding="utf-8")
print("OK app/routers/logs.py criado")


# ============================================================
# 3. Registrar logs router e handler global no app/main.py
# ============================================================

main_path = BASE / "app" / "main.py"
main = main_path.read_text(encoding="utf-8")

backup_main = main_path.with_suffix(".py.bak_logs")
if not backup_main.exists():
    backup_main.write_text(main, encoding="utf-8")

if "app.routers import logs" not in main:
    main += r'''

# Router de visualizacao de logs
try:
    from app.routers import logs
    app.include_router(logs.router)
except Exception as exc:
    print(f"Erro ao carregar router Logs: {exc}")
'''

if "@app.exception_handler(Exception)" not in main:
    main += r'''

# Handler global de erros detalhados
try:
    from fastapi import Request
    from fastapi.responses import HTMLResponse
    from app.logging_utils import log_error

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        error_id = log_error(
            contexto="ERRO_GLOBAL_FASTAPI",
            exc=exc,
            extra={
                "url": str(request.url),
                "method": request.method,
                "headers": dict(request.headers),
            },
            excel=False,
        )

        html = f"""
        <!doctype html>
        <html lang="pt-br">
        <head>
            <meta charset="utf-8">
            <title>Erro no sistema</title>
            <style>
                body {{
                    margin: 0;
                    background: #0f172a;
                    color: #e5e7eb;
                    font-family: Arial, sans-serif;
                }}
                .card {{
                    max-width: 780px;
                    margin: 60px auto;
                    background: #111827;
                    border: 1px solid #374151;
                    border-radius: 18px;
                    padding: 26px;
                }}
                code {{
                    color: #fca5a5;
                    font-weight: 700;
                }}
                a {{
                    color: white;
                    background: #dc2626;
                    padding: 10px 14px;
                    border-radius: 10px;
                    text-decoration: none;
                    font-weight: 700;
                    display: inline-block;
                    margin-top: 14px;
                    margin-right: 10px;
                }}
            </style>
        </head>
        <body>
            <div class="card">
                <h1>Erro no sistema</h1>
                <p>O erro foi registrado com o ID:</p>
                <p><code>{error_id}</code></p>
                <p>Abra o log para ver o detalhe técnico.</p>
                <a href="/logs/geral">Ver log geral</a>
                <a href="/">Voltar ao sistema</a>
            </div>
        </body>
        </html>
        """
        return HTMLResponse(html, status_code=500)

except Exception as exc:
    print(f"Erro ao configurar handler global: {exc}")
'''

main_path.write_text(main, encoding="utf-8")
print("OK app/main.py ajustado")


# ============================================================
# 4. Injetar logging detalhado dentro do excel.py
# ============================================================

excel_path = BASE / "app" / "routers" / "excel.py"

if not excel_path.exists():
    raise SystemExit("app/routers/excel.py não encontrado")

excel = excel_path.read_text(encoding="utf-8")

backup_excel = excel_path.with_suffix(".py.bak_logs")
if not backup_excel.exists():
    backup_excel.write_text(excel, encoding="utf-8")

if "from app.logging_utils import log_error" not in excel:
    excel = excel.replace(
        "from fastapi.responses import HTMLResponse, StreamingResponse",
        "from fastapi.responses import HTMLResponse, StreamingResponse\nfrom app.logging_utils import log_error",
    )

# Melhora erro de leitura do Excel
old = '''    try:
        headers, rows = read_rows_from_excel(content)
    except Exception as exc:
        return HTMLResponse(f"Erro ao ler Excel: {exc}", status_code=400)
'''

new = '''    try:
        headers, rows = read_rows_from_excel(content)
    except Exception as exc:
        error_id = log_error(
            contexto="ERRO_AO_LER_EXCEL",
            exc=exc,
            extra={
                "entity_key": entity_key,
                "arquivo": arquivo.filename,
            },
            excel=True,
        )
        return HTMLResponse(
            f"""
            <h1>Erro ao ler Excel</h1>
            <p><b>ID do erro:</b> {error_id}</p>
            <p><b>Arquivo:</b> {arquivo.filename}</p>
            <p><b>Mensagem:</b> {exc}</p>
            <p><a href='/logs/excel'>Ver log detalhado</a></p>
            <p><a href='/excel/'>Voltar</a></p>
            """,
            status_code=400,
        )
'''

if old in excel:
    excel = excel.replace(old, new)
else:
    print("AVISO: trecho de leitura do Excel não localizado exatamente. Mantendo como está.")

# Melhora erro de tabela inexistente
old2 = '''        if not table_exists(conn, cfg["table"]):
            return HTMLResponse(
                f"Tabela não encontrada no banco: {cfg['table']}",
                status_code=400,
            )
'''

new2 = '''        if not table_exists(conn, cfg["table"]):
            error_id = log_error(
                contexto="TABELA_NAO_ENCONTRADA_IMPORTACAO",
                exc=Exception(f"Tabela não encontrada no banco: {cfg['table']}"),
                extra={
                    "entity_key": entity_key,
                    "table": cfg["table"],
                    "arquivo": arquivo.filename,
                },
                excel=True,
            )
            return HTMLResponse(
                f"""
                <h1>Tabela não encontrada no banco</h1>
                <p><b>ID do erro:</b> {error_id}</p>
                <p><b>Tabela:</b> {cfg['table']}</p>
                <p><a href='/logs/excel'>Ver log detalhado</a></p>
                <p><a href='/excel/'>Voltar</a></p>
                """,
                status_code=400,
            )
'''

if old2 in excel:
    excel = excel.replace(old2, new2)
else:
    print("AVISO: trecho de tabela inexistente não localizado exatamente. Mantendo como está.")

# Melhora erro por linha dentro da importação
old3 = '''            except Exception as exc:
                erros.append({
                    "linha": linha,
                    "erro": str(exc),
                })
'''

new3 = '''            except Exception as exc:
                error_id = log_error(
                    contexto="ERRO_LINHA_IMPORTACAO_EXCEL",
                    exc=exc,
                    extra={
                        "entity_key": entity_key,
                        "table": cfg["table"],
                        "arquivo": arquivo.filename,
                        "linha_excel": linha,
                        "row": row,
                    },
                    excel=True,
                )
                erros.append({
                    "linha": linha,
                    "erro": str(exc),
                    "error_id": error_id,
                })
'''

if old3 in excel:
    excel = excel.replace(old3, new3)
else:
    print("AVISO: trecho de erro por linha não localizado exatamente. Mantendo como está.")

# Melhora HTML de erros para mostrar ID
old4 = '''        for e in erros[:100]:
            linhas += f"<tr><td>{e['linha']}</td><td>{e['erro']}</td></tr>"
'''

new4 = '''        for e in erros[:100]:
            linhas += f"<tr><td>{e.get('linha')}</td><td>{e.get('error_id', '')}</td><td>{e.get('erro')}</td></tr>"
'''

if old4 in excel:
    excel = excel.replace(old4, new4)

old5 = '''                <tr><th>Linha Excel</th><th>Erro</th></tr>'''
new5 = '''                <tr><th>Linha Excel</th><th>ID do Erro</th><th>Erro</th></tr>'''

if old5 in excel:
    excel = excel.replace(old5, new5)

excel_path.write_text(excel, encoding="utf-8")
print("OK app/routers/excel.py ajustado com logs detalhados")


# ============================================================
# 5. Testar carregamento
# ============================================================

print("")
print("PATCH FINALIZADO.")
print("Arquivos de log:")
print(" - logs/erros_detalhados.log")
print(" - logs/excel_import_errors.log")
print("")
print("Rotas novas:")
print(" - http://127.0.0.1:8000/logs/")
print(" - http://127.0.0.1:8000/logs/excel")
print(" - http://127.0.0.1:8000/logs/geral")
