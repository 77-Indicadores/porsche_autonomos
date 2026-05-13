from pathlib import Path
import re

BASE = Path(__file__).resolve().parent
BASE_HTML = BASE / "app" / "templates" / "base.html"

if not BASE_HTML.exists():
    raise SystemExit("Arquivo app/templates/base.html não encontrado.")

content = BASE_HTML.read_text(encoding="utf-8")

backup = BASE_HTML.with_suffix(".html.bak_menu_cargos")
if not backup.exists():
    backup.write_text(content, encoding="utf-8")

# Remove duplicidade caso já tenha sido inserido em algum lugar errado
content = content.replace("('/cargos-autonomos','Cargos de Autônomos'),", "")
content = content.replace("('/cargos-autonomos','Cargos Autônomos'),", "")
content = content.replace("('/cargos-autonomos','Cargos'),", "")

# Insere dentro do grupo Cadastros, logo depois de Autônomos
patterns = [
    "('/autonomos','Autônomos'),",
    "('/autonomos','Autonomos'),",
]

inserted = False

for p in patterns:
    if p in content:
        content = content.replace(
            p,
            p + "('/cargos-autonomos','Cargos de Autônomos'),"
        )
        inserted = True
        break

if not inserted:
    # Fallback: tenta inserir antes de Etapas dentro do grupo Cadastros
    content = content.replace(
        "('/etapas','Etapas'),",
        "('/cargos-autonomos','Cargos de Autônomos'),('/etapas','Etapas'),"
    )

BASE_HTML.write_text(content, encoding="utf-8")

print("OK - Cargos de Autônomos adicionado no menu lateral em Cadastros.")
print("Teste depois de reiniciar:")
print("http://127.0.0.1:8000/cargos-autonomos")
