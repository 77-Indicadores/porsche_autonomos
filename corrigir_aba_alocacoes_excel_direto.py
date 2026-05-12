from pathlib import Path

BASE = Path(__file__).resolve().parent
EXCEL = BASE / "app" / "routers" / "excel.py"

if not EXCEL.exists():
    raise SystemExit("app/routers/excel.py não encontrado")

content = EXCEL.read_text(encoding="utf-8")

backup = EXCEL.with_suffix(".py.bak_fix_sheet_direct")
if not backup.exists():
    backup.write_text(content, encoding="utf-8")

old = 'ws.title = cfg["label"][:31]'

new = '''sheet_title = str(cfg["label"])
    for invalid in [":", "\\\\", "/", "?", "*", "[", "]"]:
        sheet_title = sheet_title.replace(invalid, "-")
    sheet_title = sheet_title.strip() or "Planilha"
    ws.title = sheet_title[:31]'''

if old not in content:
    print("AVISO: linha antiga não encontrada.")
    print("Procurando ocorrência de ws.title...")
    for i, line in enumerate(content.splitlines(), start=1):
        if "ws.title" in line:
            print(i, line)
else:
    content = content.replace(old, new)
    EXCEL.write_text(content, encoding="utf-8")
    print("OK - linha ws.title corrigida.")

print("")
print("Teste rápido importando make_template...")
import sys
vendor = BASE / ".vendor"
if vendor.exists():
    sys.path.insert(0, str(vendor))

from app.routers.excel import make_template

wb = make_template("alocacoes")
print("OK - modelo alocacoes gerado.")
print("Nome da aba:", wb.sheetnames[0])
