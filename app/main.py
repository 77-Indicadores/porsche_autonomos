import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse

from app.auth import SESSION_COOKIE, read_session_token
from app.database import Base, engine, limpar_datas_vazias_sqlite
from app.routers import alocacoes, auth, cadastros, dashboard, relatorios, usuarios, referencias_importacao, pesquisas, composicao_padrao, equipe_geral, dho


Base.metadata.create_all(bind=engine)
limpar_datas_vazias_sqlite()

app = FastAPI(title="Porsche Cup Autonomos")


# ============================================================
# AUTO LOGIN LOCAL / DEMO
# ============================================================
@app.middleware("http")
async def auto_login_local_middleware(request, call_next):
    """
    Modo demo/local.
    Deixa o sistema logado automaticamente como admin@local quando
    AUTO_LOGIN_LOCAL=1 no arquivo .env ou variável de ambiente.
    """
    try:
        auto_login = os.getenv("AUTO_LOGIN_LOCAL", "1")
        if auto_login == "1":
            request.state.user = {
                "email": os.getenv("AUTO_LOGIN_EMAIL", "admin@local"),
                "nome": os.getenv("AUTO_LOGIN_NOME", "Administrador Local"),
                "perfil": "admin",
                "is_authenticated": True,
            }
    except Exception:
        pass

    return await call_next(request)

app.mount("/static", StaticFiles(directory="app/static"), name="static")


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        public_paths = {"/auth/login", "/docs", "/openapi.json", "/redoc"}
        if request.url.path.startswith("/static") or request.url.path in public_paths:
            return await call_next(request)

        token = request.cookies.get(SESSION_COOKIE)
        session_user = read_session_token(token) if token else None
        request.state.current_user = session_user
        if session_user is None:
            return RedirectResponse("/auth/login", status_code=303)

        return await call_next(request)


app.add_middleware(AuthMiddleware)

app.include_router(dashboard.router)
app.include_router(dho.router)
app.include_router(cadastros.router)
app.include_router(equipe_geral.router)
app.include_router(alocacoes.router)
app.include_router(composicao_padrao.router)
app.include_router(relatorios.router)
app.include_router(pesquisas.router)
app.include_router(auth.router)
app.include_router(usuarios.router)


# Router de visualizacao de logs
try:
    from app.routers import logs
    app.include_router(logs.router)
except Exception as exc:
    print(f"Erro ao carregar router Logs: {exc}")


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

# ============================================================

# ============================================================
try:
    import traceback
    

    
    print("OK - Router Excel registrado.")

except Exception as exc:
    print("ERRO AO CARREGAR ROUTER EXCEL")
    print(exc)
    print(traceback.format_exc())

    try:
        from app.logging_utils import log_error
        log_error(
            contexto="ERRO_AO_CARREGAR_ROUTER_EXCEL",
            exc=exc,
            extra={},
            excel=True,
        )
    except Exception as log_exc:
        print(f"Também falhou ao gravar log do erro Excel: {log_exc}")


# Rota de diagnóstico para listar rotas carregadas
try:
    from fastapi.responses import HTMLResponse

    @app.get("/debug/rotas", response_class=HTMLResponse)
    def debug_rotas():
        linhas = []
        for r in app.routes:
            path = getattr(r, "path", "")
            methods = ",".join(sorted(getattr(r, "methods", []) or []))
            name = getattr(r, "name", "")
            linhas.append(f"<tr><td>{path}</td><td>{methods}</td><td>{name}</td></tr>")

        html = f"""
        <!doctype html>
        <html lang="pt-br">
        <head>
            <meta charset="utf-8">
            <title>Rotas carregadas</title>
            <style>
                body {{ font-family: Arial; background:#0f172a; color:#e5e7eb; padding:24px; }}
                table {{ width:100%; border-collapse:collapse; background:#111827; }}
                th, td {{ padding:10px; border-bottom:1px solid #374151; text-align:left; }}
                th {{ color:#fca5a5; }}
                a {{ color:#fca5a5; }}
            </style>
        </head>
        <body>
            <h1>Rotas carregadas no FastAPI</h1>
            <p><a href="/">Voltar</a> | <a href="/logs/excel">Log Excel</a></p>
            <table>
                <thead>
                    <tr><th>Rota</th><th>Métodos</th><th>Nome</th></tr>
                </thead>
                <tbody>{''.join(linhas)}</tbody>
            </table>
        </body>
        </html>
        """
        return HTMLResponse(html)

except Exception as exc:
    print(f"Erro ao criar /debug/rotas: {exc}")

# ============================================================
# Rotas Excel registradas diretamente no main.py
# ============================================================
try:
    import importlib
    from fastapi import UploadFile, File
    from fastapi.responses import HTMLResponse

    excel_runtime = importlib.import_module("app.routers.excel")

    @app.get("/excel/", response_class=HTMLResponse)
    def excel_home_direto():
        return excel_runtime.excel_home()

    @app.get("/excel/modelo/{entity_key}")
    def baixar_modelo_excel_direto(entity_key: str):
        return excel_runtime.baixar_modelo(entity_key)

    @app.post("/excel/importar/{entity_key}", response_class=HTMLResponse)
    async def importar_excel_direto(entity_key: str, arquivo: UploadFile = File(...)):
        return await excel_runtime.importar_excel(entity_key, arquivo)

    print("OK - Rotas Excel registradas diretamente no main.py.")

except Exception as exc:
    import traceback
    print("ERRO AO REGISTRAR ROTAS EXCEL DIRETAS")
    print(exc)
    print(traceback.format_exc())

    try:
        from app.logging_utils import log_error
        log_error(
            contexto="ERRO_AO_REGISTRAR_ROTAS_EXCEL_DIRETAS",
            exc=exc,
            extra={},
            excel=True,
        )
    except Exception:
        pass

# ============================================================
# Rotas UX: Setup Inicial e Alocação Guiada
# ============================================================
try:
    import importlib

    setup_runtime = importlib.import_module("app.routers.setup")
    wizard_runtime = importlib.import_module("app.routers.wizard")

    app.include_router(setup_runtime.router)
    app.include_router(wizard_runtime.router)

    print("OK - Rotas UX registradas: /setup e /operacao/nova-guiada")

except Exception as exc:
    import traceback
    print("ERRO AO REGISTRAR ROTAS UX")
    print(exc)
    print(traceback.format_exc())

    try:
        from app.logging_utils import log_error
        log_error("ERRO_AO_REGISTRAR_ROTAS_UX", exc, {}, excel=False)
    except Exception:
        pass

# ============================================================
# Rota visual de equipes
# ============================================================
try:
    import importlib
    equipes_runtime = importlib.import_module("app.routers.equipes")
    app.include_router(equipes_runtime.router)
    print("OK - Rota /equipes registrada.")
except Exception as exc:
    import traceback
    print("ERRO AO REGISTRAR /equipes")
    print(exc)
    print(traceback.format_exc())


# ============================================================
# Router Cadastro de Carros
# ============================================================
try:
    import importlib
    carros_runtime = importlib.import_module("app.routers.carros")
    app.include_router(carros_runtime.router)

    print("OK - Rota /carros registrada.")
except Exception as exc:
    import traceback
    print("ERRO AO REGISTRAR /carros")
    print(exc)
    print(traceback.format_exc())

# Rota de referência de IDs para importação Excel
app.include_router(referencias_importacao.router)
