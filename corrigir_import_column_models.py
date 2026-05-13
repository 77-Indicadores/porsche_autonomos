from pathlib import Path
import re

BASE = Path(__file__).resolve().parent
MODELS = BASE / "app" / "models.py"

if not MODELS.exists():
    raise SystemExit("app/models.py não encontrado")

content = MODELS.read_text(encoding="utf-8")

backup = MODELS.with_suffix(".py.bak_fix_column")
if not backup.exists():
    backup.write_text(content, encoding="utf-8")

# Corrige import do SQLAlchemy para garantir Column e String
if "from sqlalchemy import" in content:
    lines = content.splitlines()
    new_lines = []

    fixed = False

    for line in lines:
        if line.startswith("from sqlalchemy import"):
            imports = line.replace("from sqlalchemy import", "").strip()
            parts = [p.strip() for p in imports.split(",") if p.strip()]

            for item in ["Column", "String"]:
                if item not in parts:
                    parts.append(item)

            line = "from sqlalchemy import " + ", ".join(parts)
            fixed = True

        new_lines.append(line)

    content = "\n".join(new_lines) + "\n"

    if fixed:
        MODELS.write_text(content, encoding="utf-8")
        print("OK - import sqlalchemy corrigido com Column e String.")
else:
    content = "from sqlalchemy import Column, String\n" + content
    MODELS.write_text(content, encoding="utf-8")
    print("OK - import sqlalchemy adicionado.")

# Testa import do app
import sys
vendor = BASE / ".vendor"
if vendor.exists():
    sys.path.insert(0, str(vendor))

from app.main import app

print("OK - app carregado novamente.")
