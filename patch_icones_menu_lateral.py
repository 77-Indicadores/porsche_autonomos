from pathlib import Path

BASE = Path(__file__).resolve().parent
BASE_HTML = BASE / "app" / "templates" / "base.html"
CSS_FILE = BASE / "app" / "static" / "css" / "style.css"

if not BASE_HTML.exists():
    raise SystemExit("Arquivo app/templates/base.html não encontrado.")

content = BASE_HTML.read_text(encoding="utf-8")

backup = BASE_HTML.with_suffix(".html.bak_icons")
if not backup.exists():
    backup.write_text(content, encoding="utf-8")

replacements = {
    "Controle de Autonomos": "🏎️ Controle de Autônomos",
    "Controle de Autônomos": "🏎️ Controle de Autônomos",

    "('\/','Visão Geral')": "('/','🏠 Visão Geral')",
    "('\/','Visao Geral')": "('/','🏠 Visão Geral')",

    "('/setup','Setup Inicial')": "('/setup','🧱 Setup Inicial')",

    "('/pilotos','Pilotos')": "('/pilotos','👨‍✈️ Pilotos')",
    "('/autonomos','Autônomos')": "('/autonomos','🧰 Autônomos')",
    "('/autonomos','Autonomos')": "('/autonomos','🧰 Autônomos')",
    "('/cargos-autonomos','Cargos de Autônomos')": "('/cargos-autonomos','🪪 Cargos de Autônomos')",
    "('/cargos-autonomos','Cargos Autônomos')": "('/cargos-autonomos','🪪 Cargos de Autônomos')",
    "('/etapas','Etapas')": "('/etapas','📍 Etapas')",
    "('/provas','Categorias')": "('/provas','🏁 Categorias')",
    "('/tipos-prova','Tipos de Categoria')": "('/tipos-prova','🗂️ Tipos de Categoria')",
    "('/motivos-troca','Motivos de Troca')": "('/motivos-troca','🔄 Motivos de Troca')",

    "('/operacao/nova-guiada','Nova Alocação Guiada')": "('/operacao/nova-guiada','✨ Nova Alocação Guiada')",
    "('/alocacoes','Gestão de Alocação')": "('/alocacoes','📋 Gestão de Alocação')",
    "('/relatorios/trocas','Trocas')": "('/relatorios/trocas','🔁 Trocas')",

    "('/excel/','Importações Excel')": "('/excel/','📥 Importações Excel')",
    "('/logs/','Logs do Sistema')": "('/logs/','🧾 Logs do Sistema')",
    "('/debug/rotas','Rotas Técnicas')": "('/debug/rotas','🛠️ Rotas Técnicas')",
    "('/tipos-prova','Listas de Apoio')": "('/tipos-prova','⚙️ Listas de Apoio')",
}

for old, new in replacements.items():
    content = content.replace(old, new)

BASE_HTML.write_text(content, encoding="utf-8")
print("OK - Ícones adicionados ao menu lateral.")

# Ajuste opcional no CSS para dar mais respiro
if CSS_FILE.exists():
    css = CSS_FILE.read_text(encoding="utf-8")
    if ".nav-link" in css and "letter-spacing" not in css:
        css += """

/* Menu com ícones */
.nav-link {
  display: flex;
  align-items: center;
  gap: .55rem;
}
"""
        CSS_FILE.write_text(css, encoding="utf-8")
        print("OK - CSS ajustado para o menu com ícones.")
    else:
        print("CSS já possui ajuste ou não foi necessário.")
else:
    print("AVISO - style.css não encontrado. Menu foi ajustado sem CSS extra.")

print("")
print("Reinicie o servidor e teste:")
print("http://127.0.0.1:8000/")
