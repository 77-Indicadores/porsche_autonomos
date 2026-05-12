from pathlib import Path
import re

BASE = Path(__file__).resolve().parent
MAIN = BASE / "app" / "main.py"

if not MAIN.exists():
    raise SystemExit("app/main.py não encontrado")

main = MAIN.read_text(encoding="utf-8")

backup = MAIN.with_suffix(".py.bak_excel_direto")
if not backup.exists():
    backup.write_text(main, encoding="utf-8")

# Remove blocos antigos de Excel para evitar conflito
main = re.sub(
    r"\n# ============================================================\n# Router Excel.*?(?=\n# ============================================================|\n# Router|\n# Handler|\Z)",
    "\n",
    main,
    flags=re.DOTALL,
)

main = re.sub(
    r"\n# Router de importacao/exportacao Excel.*?(?=\n#|\Z)",
    "\n",
    main,
    flags=re.DOTALL,
)

main = main.replace("from app.routers import excel", "")
main = main.replace("app.include_router(excel.router)", "")

direct_block = r'''

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
'''

main = main.rstrip() + direct_block + "\n"

MAIN.write_text(main, encoding="utf-8")

print("OK - main.py atualizado com rotas Excel diretas.")

# Teste rápido
import sys
vendor = BASE / ".vendor"
if vendor.exists():
    sys.path.insert(0, str(vendor))

from app.main import app

rotas = [getattr(r, "path", "") for r in app.routes]
rotas_excel = [r for r in rotas if r.startswith("/excel")]

print("ROTAS EXCEL ENCONTRADAS:")
for r in rotas_excel:
    print(" -", r)

if not rotas_excel:
    raise SystemExit("ERRO: as rotas /excel ainda não apareceram.")

print("OK FINAL - /excel disponível.")
