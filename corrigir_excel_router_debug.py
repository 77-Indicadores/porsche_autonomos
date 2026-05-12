from pathlib import Path

BASE = Path(__file__).resolve().parent
MAIN = BASE / "app" / "main.py"

main = MAIN.read_text(encoding="utf-8")

backup = MAIN.with_suffix(".py.bak_excel_debug")
if not backup.exists():
    backup.write_text(main, encoding="utf-8")

# Remove blocos antigos simples do Excel, se existirem parcialmente
lines = main.splitlines()
new_lines = []
skip = False

for line in lines:
    if "# Router de importacao/exportacao Excel" in line:
        skip = True
        continue

    if skip:
        # para de pular quando chegar em outro bloco conhecido
        if line.startswith("# Router de visualizacao de logs") or line.startswith("# Handler global"):
            skip = False
            new_lines.append(line)
        else:
            continue
    else:
        new_lines.append(line)

main = "\n".join(new_lines)

debug_block = r'''

# ============================================================
# Router de importacao/exportacao Excel - DEBUG ROBUSTO
# ============================================================
try:
    import traceback
    from app.routers import excel

    app.include_router(excel.router)
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
'''

main = main.rstrip() + debug_block + "\n"

MAIN.write_text(main, encoding="utf-8")

print("OK - main.py ajustado para debug do router Excel.")
print("Agora reinicie o servidor.")
