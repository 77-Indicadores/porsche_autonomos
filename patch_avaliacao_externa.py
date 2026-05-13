from pathlib import Path
import re

BASE = Path(__file__).resolve().parent

def backup(path):
    if path.exists():
        bkp = path.with_suffix(path.suffix + ".bak_avaliacao_externa")
        if not bkp.exists():
            bkp.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")

def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")

# ============================================================
# 1. Adicionar campo no banco SQLite
# ============================================================

db_path = BASE / "data" / "app.db"

if db_path.exists():
    import sqlite3
    conn = sqlite3.connect(db_path)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(fato_piloto_autonomo_prova)").fetchall()]

    if "link_avaliacao_externa" not in cols:
        conn.execute("ALTER TABLE fato_piloto_autonomo_prova ADD COLUMN link_avaliacao_externa TEXT")
        conn.commit()
        print("OK - coluna link_avaliacao_externa criada no banco.")
    else:
        print("OK - coluna link_avaliacao_externa já existe.")

    conn.close()
else:
    print("AVISO - data/app.db não encontrado. O campo será usado no modelo/tela, mas o banco local não foi alterado.")


# ============================================================
# 2. Atualizar model se possível
# ============================================================

models_path = BASE / "app" / "models.py"
backup(models_path)

models = models_path.read_text(encoding="utf-8")

if "link_avaliacao_externa" not in models:
    marker = "comentario_avaliacao"
    lines = models.splitlines()
    new_lines = []

    inserted = False

    for line in lines:
        new_lines.append(line)

        if marker in line and not inserted:
            indent = line[:len(line) - len(line.lstrip())]
            new_lines.append(f'{indent}link_avaliacao_externa = Column(String)')
            inserted = True

    if inserted:
        models_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        print("OK - models.py atualizado com link_avaliacao_externa.")
    else:
        print("AVISO - não encontrei comentario_avaliacao no models.py. Não alterei o model.")
else:
    print("OK - models.py já possui link_avaliacao_externa.")


# ============================================================
# 3. Atualizar router de alocações
# ============================================================

aloc_path = BASE / "app" / "routers" / "alocacoes.py"
backup(aloc_path)

aloc = aloc_path.read_text(encoding="utf-8")

# Garante Form já existe. O arquivo já usa Form, então ok.

if "link_avaliacao_form" not in aloc:
    bloco = r'''

@router.get("/alocacoes/{id_fato}/link-avaliacao")
def link_avaliacao_form(id_fato: int, request: Request, db: Session = Depends(get_db)):
    fato = db.get(FatoPilotoAutonomoProva, id_fato)

    if not fato:
        return redirect_with_message("/alocacoes", error="Alocação não encontrada.")

    return templates.TemplateResponse(
        "alocacoes/link_avaliacao.html",
        {
            "request": request,
            "fato": fato,
            **flash_from_request(request),
        },
    )


@router.post("/alocacoes/{id_fato}/link-avaliacao")
def link_avaliacao_salvar(
    id_fato: int,
    link_avaliacao_externa: str = Form(""),
    db: Session = Depends(get_db),
):
    fato = db.get(FatoPilotoAutonomoProva, id_fato)

    if not fato:
        return redirect_with_message("/alocacoes", error="Alocação não encontrada.")

    fato.link_avaliacao_externa = link_avaliacao_externa.strip() or None
    db.commit()

    return redirect_with_message("/alocacoes", success="Link externo de avaliação salvo.")
'''
    aloc = aloc.rstrip() + bloco + "\n"
    print("OK - rotas de link externo adicionadas.")
else:
    print("OK - rotas de link externo já existem.")

aloc_path.write_text(aloc, encoding="utf-8")


# ============================================================
# 4. Criar template de link externo
# ============================================================

link_template = r'''{% extends "base.html" %}

{% block header %}Link Externo da Avaliação{% endblock %}
{% block subtitle %}A avaliação do autônomo será feita fora deste sistema{% endblock %}

{% block content %}

<section class="ux-card mb-6">
  <h3 class="ux-card-title">Alocação</h3>
  <p><b>Piloto:</b> {{ fato.piloto.nome_piloto }}</p>
  <p><b>Prova:</b> {{ fato.prova.nome_prova }}</p>
  <p><b>Função:</b> {{ fato.funcao_autonomo }}</p>
  <p><b>Autônomo:</b> {{ fato.autonomo.nome_autonomo }}</p>
</section>

<section class="panel">
  <div class="panel-head">
    <div>
      <h3>Link da avaliação externa</h3>
      <p class="text-sm text-zinc-500">
        Cole aqui o link do Google Forms, Microsoft Forms, Typeform ou outro formulário externo.
      </p>
    </div>
  </div>

  <form method="post" class="form-grid">
    <div class="span-3">
      <label class="label">URL da avaliação</label>
      <input
        class="input"
        name="link_avaliacao_externa"
        placeholder="https://..."
        value="{{ fato.link_avaliacao_externa or '' }}"
      >
    </div>

    <div class="span-3 ux-actions-row">
      <a class="btn-muted" href="/alocacoes">Voltar</a>

      {% if fato.link_avaliacao_externa %}
        <a class="btn-secondary" href="{{ fato.link_avaliacao_externa }}" target="_blank">Abrir avaliação</a>
      {% endif %}

      <button class="btn-primary">Salvar link</button>
    </div>
  </form>
</section>

<div class="ux-help mt-6">
  As notas e respostas da avaliação não serão armazenadas neste sistema. Este sistema guarda apenas o vínculo operacional e o link externo.
</div>

{% endblock %}
'''

write(BASE / "app" / "templates" / "alocacoes" / "link_avaliacao.html", link_template)
print("OK - template link_avaliacao.html criado.")


# ============================================================
# 5. Atualizar tela de alocações
# ============================================================

list_path = BASE / "app" / "templates" / "alocacoes" / "list.html"
backup(list_path)

list_html = list_path.read_text(encoding="utf-8")

# Troca botão Avaliar por Link Avaliação.
list_html = list_html.replace(
    '<a class="btn-muted" href="/alocacoes/{{ f.id_fato }}/avaliar">Avaliar</a>',
    '<a class="btn-muted" href="/alocacoes/{{ f.id_fato }}/link-avaliacao">Link avaliação</a>'
)

list_html = list_html.replace(
    '<a class="btn-muted" href="/alocacoes/{{ f.id_fato }}/avaliar">Avaliar</a>',
    '<a class="btn-muted" href="/alocacoes/{{ f.id_fato }}/link-avaliacao">Link avaliação</a>'
)

# Troca coluna Nota por Avaliação externa, quando existir.
list_html = list_html.replace("<th>Nota</th>", "<th>Avaliação</th>")
list_html = list_html.replace(
    "<td>{{ f.nota_geral or '-' }}</td>",
    """<td>
            {% if f.link_avaliacao_externa %}
              <a class="ux-pill green" href="{{ f.link_avaliacao_externa }}" target="_blank">Abrir link</a>
            {% else %}
              <span class="ux-pill yellow">Sem link</span>
            {% endif %}
          </td>"""
)

list_path.write_text(list_html, encoding="utf-8")
print("OK - tela de alocações atualizada.")


# ============================================================
# 6. Ajustar base.html: remover Avaliações do menu
# ============================================================

base_path = BASE / "app" / "templates" / "base.html"
backup(base_path)

base = base_path.read_text(encoding="utf-8")

base = base.replace("('/relatorios/avaliacoes','Avaliações'),", "")
base = base.replace("('/relatorios/avaliacoes','Avaliacoes'),", "")

base_path.write_text(base, encoding="utf-8")
print("OK - menu ajustado sem Avaliações.")


# ============================================================
# 7. Criar página informativa opcional para rota antiga
# ============================================================

relatorio_avaliacoes = r'''{% extends "base.html" %}

{% block header %}Avaliações Externas{% endblock %}
{% block subtitle %}As avaliações dos autônomos são realizadas fora deste sistema{% endblock %}

{% block content %}
<section class="ux-card">
  <h3 class="ux-card-title">Avaliação externa</h3>
  <p class="ux-muted">
    Este sistema não registra notas de avaliação dos autônomos. As avaliações são feitas por link externo.
  </p>

  <div class="ux-actions-row mt-5">
    <a class="btn-primary" href="/alocacoes">Ir para Gestão de Alocação</a>
    <a class="btn-muted" href="/setup">Setup Inicial</a>
  </div>
</section>
{% endblock %}
'''

write(BASE / "app" / "templates" / "relatorios" / "avaliacoes.html", relatorio_avaliacoes)
print("OK - página antiga de avaliações virou informativo.")


# ============================================================
# 8. Teste rápido
# ============================================================

import sys
vendor = BASE / ".vendor"
if vendor.exists():
    sys.path.insert(0, str(vendor))

from app.main import app

rotas = sorted([getattr(r, "path", "") for r in app.routes])

print("")
print("Rotas de avaliação externa:")
for r in rotas:
    if "link-avaliacao" in r:
        print(" -", r)

print("")
print("PATCH CONCLUÍDO.")
print("Reinicie o servidor e teste:")
print(" - http://127.0.0.1:8000/alocacoes")
