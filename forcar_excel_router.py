from pathlib import Path
import re

BASE = Path(__file__).resolve().parent
MAIN = BASE / "app" / "main.py"
EXCEL_FILE = BASE / "app" / "routers" / "excel.py"

if not MAIN.exists():
    raise SystemExit("ERRO: app/main.py não encontrado")

if not EXCEL_FILE.exists():
    raise SystemExit("ERRO: app/routers/excel.py não encontrado")

main = MAIN.read_text(encoding="utf-8")

backup = MAIN.with_suffix(".py.bak_force_excel")
if not backup.exists():
    backup.write_text(main, encoding="utf-8")

# Remove tentativas antigas de importar Excel pelo app.routers
main = re.sub(
    r"# Router de importacao/exportacao Excel.*?(?=\n#|\Z)",
    "",
    main,
    flags=re.DOTALL,
)

main = re.sub(
    r"# ============================================================\n# Router de importacao/exportacao Excel - DEBUG ROBUSTO.*?(?=\n#|\Z)",
    "",
    main,
    flags=re.DOTALL,
)

main = re.sub(
    r"# ============================================================\n# Router Excel - importação direta por módulo.*?(?=\n#|\Z)",
    "",
    main,
    flags=re.DOTALL,
)

main = main.replace("from app.routers import excel", "")
main = main.replace("app.include_router(excel.router)", "")

force_block = r'''

# ============================================================
# Router Excel - carregamento forçado por caminho do arquivo
# ============================================================
try:
    import importlib.util
    import traceback
    from pathlib import Path

    excel_path = Path(__file__).resolve().parent / "routers" / "excel.py"

    if not excel_path.exists():
        raise FileNotFoundError(f"Router Excel não encontrado em: {excel_path}")

    spec = importlib.util.spec_from_file_location("excel_router_runtime", excel_path)
    excel_runtime = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(excel_runtime)

    app.include_router(excel_runtime.router)

    print("OK - Router Excel registrado por caminho direto.")

except Exception as exc:
    print("ERRO AO CARREGAR ROUTER EXCEL POR CAMINHO DIRETO")
    print(exc)
    print(traceback.format_exc())

    try:
        from app.logging_utils import log_error
        log_error(
            contexto="ERRO_AO_CARREGAR_ROUTER_EXCEL_CAMINHO_DIRETO",
            exc=exc,
            extra={},
            excel=True,
        )
    except Exception as log_exc:
        print(f"Falha ao gravar log Excel: {log_exc}")
'''

main = main.rstrip() + force_block + "\n"

MAIN.write_text(main, encoding="utf-8")

print("OK - main.py atualizado.")
print("Agora reinicie o servidor.")
