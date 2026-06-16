
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
