from pathlib import Path
import re

BASE = Path(__file__).resolve().parent
BASE_HTML = BASE / "app" / "templates" / "base.html"

if not BASE_HTML.exists():
    raise SystemExit("Arquivo app/templates/base.html não encontrado.")

content = BASE_HTML.read_text(encoding="utf-8")

backup = BASE_HTML.with_suffix(".html.bak_remove_fin_rel")
if not backup.exists():
    backup.write_text(content, encoding="utf-8")

# ------------------------------------------------------------
# Remove grupos inteiros: Financeiro e Relatórios
# ------------------------------------------------------------

# Remove grupo Financeiro inteiro
content = re.sub(
    r"\s*\('Financeiro',\s*\[.*?\]\),?",
    "",
    content,
    flags=re.DOTALL
)

# Remove grupo Relatórios inteiro
content = re.sub(
    r"\s*\('Relatórios',\s*\[.*?\]\),?",
    "",
    content,
    flags=re.DOTALL
)

# Remove variações sem acento, caso existam
content = re.sub(
    r"\s*\('Relatorios',\s*\[.*?\]\),?",
    "",
    content,
    flags=re.DOTALL
)

# ------------------------------------------------------------
# Segurança: remove itens soltos se sobraram
# ------------------------------------------------------------

itens_remover = [
    "('/relatorios/custos','Custos por Etapa'),",
    "('/relatorios/custos','Relatorios Financeiros'),",
    "('/relatorios/custos','Relatórios Financeiros'),",
    "('/relatorios/custos','Custo por Categoria'),",
    "('/relatorios/trocas','Trocas por Motivo'),",
    "('/relatorios/avaliacoes','Avaliacoes'),",
    "('/relatorios/avaliacoes','Avaliações'),",
]

for item in itens_remover:
    content = content.replace(item, "")

# Limpeza de vírgulas duplas em listas
content = content.replace(",\n          ,", ",")
content = content.replace("[,", "[")

BASE_HTML.write_text(content, encoding="utf-8")

print("OK - Menus Financeiro e Relatórios removidos do menu lateral.")
print("")
print("Agora reinicie o servidor e teste:")
print("http://127.0.0.1:8000/")
