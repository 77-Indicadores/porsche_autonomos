from pathlib import Path
import re

BASE = Path(__file__).resolve().parent

# ------------------------------------------------------------
# Blocos HTML
# ------------------------------------------------------------

MENU_LINK = '''
<a href="/excel/" class="nav-link excel-menu-link">
    <span>📥</span>
    <span>Importações Excel</span>
</a>
'''

CSS_BLOCK = '''
<style>
.excel-import-box {
    margin: 16px 0 22px 0;
    padding: 16px;
    border-radius: 16px;
    background: rgba(220, 38, 38, .08);
    border: 1px solid rgba(220, 38, 38, .25);
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 12px;
}

.excel-import-box .excel-title {
    font-weight: 800;
    color: #fca5a5;
    margin-right: 8px;
}

.excel-import-box a,
.excel-import-box button {
    border: 0;
    border-radius: 10px;
    padding: 9px 12px;
    font-weight: 700;
    text-decoration: none;
    cursor: pointer;
}

.excel-import-box a {
    background: #dc2626;
    color: #fff;
}

.excel-import-box button {
    background: #374151;
    color: #fff;
}

.excel-import-box input[type=file] {
    color: inherit;
    max-width: 260px;
}

.excel-menu-link {
    margin-top: 10px;
}
</style>
'''

def excel_box(entity_key, label):
    return f'''
<div class="excel-import-box">
    <span class="excel-title">Excel - {label}</span>

    <a href="/excel/modelo/{entity_key}">
        Baixar modelo
    </a>

    <form action="/excel/importar/{entity_key}" method="post" enctype="multipart/form-data" style="display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin:0;">
        <input type="file" name="arquivo" accept=".xlsx" required>
        <button type="submit">Importar Excel</button>
    </form>
</div>
'''

# ------------------------------------------------------------
# Utilitários
# ------------------------------------------------------------

def read(path):
    return path.read_text(encoding="utf-8")

def write(path, content):
    path.write_text(content, encoding="utf-8")

def backup(path):
    bkp = path.with_suffix(path.suffix + ".bak_excel")
    if not bkp.exists():
        bkp.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")

def insert_after_h1(content, block):
    if "excel-import-box" in content:
        return content

    match = re.search(r"</h1>", content, flags=re.IGNORECASE)

    if match:
        pos = match.end()
        return content[:pos] + "\n" + block + "\n" + content[pos:]

    # fallback: tenta depois do primeiro bloco de conteúdo
    match = re.search(r"<main[^>]*>", content, flags=re.IGNORECASE)
    if match:
        pos = match.end()
        return content[:pos] + "\n" + block + "\n" + content[pos:]

    # fallback final: início do arquivo
    return block + "\n" + content

# ------------------------------------------------------------
# 1. Ajustar base.html com CSS e link no menu
# ------------------------------------------------------------

base_path = BASE / "app" / "templates" / "base.html"

if base_path.exists():
    backup(base_path)
    base = read(base_path)

    if "excel-import-box" not in base:
        if "</head>" in base:
            base = base.replace("</head>", CSS_BLOCK + "\n</head>")
        else:
            base = CSS_BLOCK + "\n" + base

    if "/excel/" not in base and "/excel" not in base:
        if "</nav>" in base:
            base = base.replace("</nav>", MENU_LINK + "\n</nav>")
        elif "</aside>" in base:
            base = base.replace("</aside>", MENU_LINK + "\n</aside>")
        else:
            # fallback: coloca logo após abertura do body
            if "<body" in base:
                m = re.search(r"<body[^>]*>", base, flags=re.IGNORECASE)
                if m:
                    pos = m.end()
                    base = base[:pos] + "\n" + MENU_LINK + "\n" + base[pos:]
            else:
                base = MENU_LINK + "\n" + base

    write(base_path, base)
    print("OK base.html ajustado")
else:
    print("base.html não encontrado")

# ------------------------------------------------------------
# 2. Inserir botões nas telas principais
# ------------------------------------------------------------

targets = {
    "app/templates/cadastros/pilotos.html": ("pilotos", "Pilotos"),
    "app/templates/pilotos/list.html": ("pilotos", "Pilotos"),

    "app/templates/cadastros/autonomos.html": ("autonomos", "Autônomos"),
    "app/templates/autonomos/list.html": ("autonomos", "Autônomos"),

    "app/templates/cadastros/etapas.html": ("etapas", "Etapas"),
    "app/templates/etapas/list.html": ("etapas", "Etapas"),

    "app/templates/cadastros/tipos.html": ("tipos-prova", "Tipos de Prova"),
    "app/templates/cadastros/provas.html": ("provas", "Provas"),
    "app/templates/cadastros/motivos.html": ("motivos-troca", "Motivos de Troca"),

    "app/templates/alocacoes/list.html": ("alocacoes", "Alocações / Fato Principal"),
    "app/templates/vinculos/list.html": ("alocacoes", "Alocações / Fato Principal"),
}

for rel, (entity, label) in targets.items():
    path = BASE / rel

    if not path.exists():
        print(f"IGNORADO não encontrado: {rel}")
        continue

    backup(path)
    content = read(path)

    if "excel-import-box" in content:
        print(f"JÁ EXISTE: {rel}")
        continue

    content = insert_after_h1(content, excel_box(entity, label))
    write(path, content)
    print(f"OK botões Excel adicionados: {rel}")

print("")
print("PATCH FINALIZADO.")
print("Pare o servidor com CTRL+C e rode novamente: .\\run_server.bat")
print("Depois acesse: http://127.0.0.1:8000/")
print("Página direta de importações: http://127.0.0.1:8000/excel/")
