from pathlib import Path
import re
import sqlite3

BASE = Path(__file__).resolve().parent

def backup(path):
    if path.exists():
        bkp = path.with_suffix(path.suffix + ".bak_cargo_autonomo")
        if not bkp.exists():
            bkp.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")

def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")

# ============================================================
# 1. Banco SQLite: tabela de cargos e vínculo no autônomo
# ============================================================

db_path = BASE / "data" / "app.db"

if db_path.exists():
    conn = sqlite3.connect(db_path)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS dim_cargos_autonomos (
            id_cargo_autonomo INTEGER PRIMARY KEY AUTOINCREMENT,
            nome_cargo TEXT NOT NULL,
            descricao TEXT,
            status TEXT DEFAULT 'Ativo'
        )
    """)

    cols_autonomos = [r[1] for r in conn.execute("PRAGMA table_info(dim_autonomos)").fetchall()]

    if "id_cargo_autonomo" not in cols_autonomos:
        conn.execute("ALTER TABLE dim_autonomos ADD COLUMN id_cargo_autonomo INTEGER")

    cargos_padrao = [
        ("Mecânico", "Profissional responsável pela parte mecânica", "Ativo"),
        ("Engenheiro", "Profissional responsável pela engenharia", "Ativo"),
        ("Preparador", "Profissional responsável pela preparação", "Ativo"),
        ("Outro", "Outro tipo de cargo", "Ativo"),
    ]

    for nome, descricao, status in cargos_padrao:
        existe = conn.execute(
            "SELECT 1 FROM dim_cargos_autonomos WHERE LOWER(nome_cargo)=LOWER(?)",
            (nome,)
        ).fetchone()

        if not existe:
            conn.execute(
                "INSERT INTO dim_cargos_autonomos (nome_cargo, descricao, status) VALUES (?, ?, ?)",
                (nome, descricao, status)
            )

    # tenta associar autônomos antigos pelo campo tipo_autonomo
    conn.execute("""
        UPDATE dim_autonomos
        SET id_cargo_autonomo = (
            SELECT c.id_cargo_autonomo
            FROM dim_cargos_autonomos c
            WHERE LOWER(c.nome_cargo) = LOWER(dim_autonomos.tipo_autonomo)
            LIMIT 1
        )
        WHERE id_cargo_autonomo IS NULL
    """)

    conn.commit()
    conn.close()

    print("OK - Banco ajustado com cargos de autônomos.")
else:
    print("AVISO - data/app.db não encontrado.")

# ============================================================
# 2. models.py: adicionar campo id_cargo_autonomo no DimAutonomo
# ============================================================

models_path = BASE / "app" / "models.py"
backup(models_path)

models = models_path.read_text(encoding="utf-8")

# garante imports
if "from sqlalchemy import" in models:
    lines = models.splitlines()
    new_lines = []

    for line in lines:
        if line.startswith("from sqlalchemy import"):
            imports = line.replace("from sqlalchemy import", "").strip()
            parts = [p.strip() for p in imports.split(",") if p.strip()]
            for item in ["Column", "Integer", "String"]:
                if item not in parts:
                    parts.append(item)
            line = "from sqlalchemy import " + ", ".join(parts)

        new_lines.append(line)

    models = "\n".join(new_lines) + "\n"
else:
    models = "from sqlalchemy import Column, Integer, String\n" + models

# adiciona modelo DimCargoAutonomo se não existir
if "class DimCargoAutonomo" not in models:
    insert_class = r'''

class DimCargoAutonomo(Base):
    __tablename__ = "dim_cargos_autonomos"

    id_cargo_autonomo = Column(Integer, primary_key=True, index=True)
    nome_cargo = Column(String, nullable=False)
    descricao = Column(String)
    status = Column(String, default="Ativo")
'''

    marker = "class DimAutonomo"
    models = models.replace(marker, insert_class + "\n\n" + marker)

# adiciona coluna em DimAutonomo
if "id_cargo_autonomo" not in models:
    lines = models.splitlines()
    new_lines = []
    in_autonomo = False
    inserted = False

    for line in lines:
        if line.startswith("class DimAutonomo"):
            in_autonomo = True

        if in_autonomo and not inserted and "tipo_autonomo" in line:
            new_lines.append(line)
            indent = line[:len(line) - len(line.lstrip())]
            new_lines.append(f"{indent}id_cargo_autonomo = Column(Integer)")
            inserted = True
            continue

        if in_autonomo and line.startswith("class ") and not line.startswith("class DimAutonomo"):
            in_autonomo = False

        new_lines.append(line)

    models = "\n".join(new_lines) + "\n"

models_path.write_text(models, encoding="utf-8")
print("OK - models.py ajustado.")

# ============================================================
# 3. cadastros.py: adicionar cargo no cadastro de autônomos e novas rotas
# ============================================================

cad_path = BASE / "app" / "routers" / "cadastros.py"
backup(cad_path)

cad = cad_path.read_text(encoding="utf-8")

# import text
if "from sqlalchemy import or_" in cad and "text" not in cad.split("from sqlalchemy import", 1)[1].split("\n", 1)[0]:
    cad = cad.replace("from sqlalchemy import or_", "from sqlalchemy import or_, text")

# importa DimCargoAutonomo se a importação existir
if "DimCargoAutonomo" not in cad:
    cad = cad.replace(
        "from app.models import ",
        "from app.models import DimCargoAutonomo, "
    )

# lists com cargos
if '"cargos_autonomos"' not in cad:
    cad = cad.replace(
        '"motivos": db.query(DimMotivoTroca).order_by(DimMotivoTroca.motivo_troca).all(),',
        '"motivos": db.query(DimMotivoTroca).order_by(DimMotivoTroca.motivo_troca).all(),\n        "cargos_autonomos": db.query(DimCargoAutonomo).filter(DimCargoAutonomo.status == "Ativo").order_by(DimCargoAutonomo.nome_cargo).all(),'
    )

# autonomos GET precisa mandar cargos
cad = cad.replace(
    'return templates.TemplateResponse("cadastros/autonomos.html", {"request": request, "items": query.order_by(DimAutonomo.nome_autonomo).all(), "q": q, **flash_from_request(request)})',
    'return templates.TemplateResponse("cadastros/autonomos.html", {"request": request, "items": query.order_by(DimAutonomo.nome_autonomo).all(), "q": q, **lists(db), **flash_from_request(request)})'
)

# salvar_autonomo: adiciona id_cargo_autonomo no Form
if "id_cargo_autonomo: str = Form" not in cad:
    cad = cad.replace(
        'tipo_autonomo: str = Form("Mecanico"),',
        'tipo_autonomo: str = Form(""),\n    id_cargo_autonomo: str = Form(""),'
    )

# salvar_autonomo: grava cargo e sincroniza tipo_autonomo com nome do cargo
if "cargo_obj = db.get(DimCargoAutonomo" not in cad:
    cad = cad.replace(
        "autonomo.email = email\n    autonomo.tipo_autonomo = tipo_autonomo",
        """autonomo.email = email

    cargo_obj = db.get(DimCargoAutonomo, int(id_cargo_autonomo)) if id_cargo_autonomo else None
    autonomo.id_cargo_autonomo = int(id_cargo_autonomo) if id_cargo_autonomo else None
    autonomo.tipo_autonomo = cargo_obj.nome_cargo if cargo_obj else tipo_autonomo"""
    )

# adiciona rotas de cargos de autônomos
if '@router.get("/cargos-autonomos")' not in cad:
    cargos_routes = r'''


@router.get("/cargos-autonomos")
def cargos_autonomos(request: Request, db: Session = Depends(get_db)):
    items = db.query(DimCargoAutonomo).order_by(DimCargoAutonomo.nome_cargo).all()

    return templates.TemplateResponse(
        "cadastros/cargos_autonomos.html",
        {
            "request": request,
            "items": items,
            **flash_from_request(request),
        },
    )


@router.post("/cargos-autonomos")
def salvar_cargo_autonomo(
    id_cargo_autonomo: str = Form(""),
    nome_cargo: str = Form(...),
    descricao: str = Form(""),
    status: str = Form("Ativo"),
    db: Session = Depends(get_db),
):
    cargo = db.get(DimCargoAutonomo, int(id_cargo_autonomo)) if id_cargo_autonomo else DimCargoAutonomo()

    if not cargo:
        return redirect_with_message("/cargos-autonomos", error="Cargo não encontrado.")

    cargo.nome_cargo = nome_cargo
    cargo.descricao = descricao
    cargo.status = status

    db.add(cargo)
    db.commit()

    msg = "Cargo atualizado." if id_cargo_autonomo else "Cargo cadastrado."
    return redirect_with_message("/cargos-autonomos", success=msg)
'''

    cad = cad.rstrip() + cargos_routes + "\n"

cad_path.write_text(cad, encoding="utf-8")
print("OK - cadastros.py ajustado.")

# ============================================================
# 4. Template novo: cadastro de cargos
# ============================================================

cargos_template = r'''{% extends "base.html" %}

{% block header %}Cargos de Autônomos{% endblock %}
{% block subtitle %}Cadastre os cargos usados para filtrar autônomos na alocação{% endblock %}

{% block content %}

<section class="panel mb-6">
  <div class="panel-head">
    <div>
      <h3 id="form-title">Novo cargo</h3>
      <p class="text-sm text-zinc-500">
        Exemplos: Mecânico, Engenheiro, Preparador.
      </p>
    </div>
    <button class="btn-muted" type="button" onclick="limparCargo()">Novo</button>
  </div>

  <form method="post" class="form-grid">
    <input type="hidden" name="id_cargo_autonomo" id="id_cargo_autonomo">

    <div>
      <label class="label">Nome do cargo</label>
      <input class="input" name="nome_cargo" id="nome_cargo" required placeholder="Ex.: Mecânico">
    </div>

    <div>
      <label class="label">Status</label>
      <select class="input" name="status" id="status">
        <option>Ativo</option>
        <option>Inativo</option>
      </select>
    </div>

    <div class="span-3">
      <label class="label">Descrição</label>
      <textarea class="input" name="descricao" id="descricao"></textarea>
    </div>

    <div class="span-3 ux-actions-row">
      <button class="btn-primary" id="btn-salvar">Salvar cargo</button>
      <button class="btn-muted" type="button" onclick="limparCargo()">Limpar</button>
    </div>
  </form>
</section>

<section class="panel">
  <div class="panel-head">
    <h3>Cargos cadastrados</h3>
  </div>

  <table class="table">
    <thead>
      <tr>
        <th>Cargo</th>
        <th>Status</th>
        <th>Descrição</th>
        <th>Ações</th>
      </tr>
    </thead>

    <tbody>
      {% for i in items %}
      <tr>
        <td class="font-bold">{{ i.nome_cargo }}</td>
        <td>{{ i.status }}</td>
        <td>{{ i.descricao or '-' }}</td>
        <td>
          <button
            class="btn-muted"
            type="button"
            data-id="{{ i.id_cargo_autonomo }}"
            data-nome="{{ i.nome_cargo }}"
            data-status="{{ i.status }}"
            data-descricao="{{ i.descricao or '' }}"
            onclick="editarCargo(this)"
          >
            Editar
          </button>
        </td>
      </tr>
      {% else %}
      <tr>
        <td colspan="4" class="empty">Nenhum cargo cadastrado.</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</section>

<script>
function editarCargo(btn) {
  document.getElementById("id_cargo_autonomo").value = btn.dataset.id || "";
  document.getElementById("nome_cargo").value = btn.dataset.nome || "";
  document.getElementById("status").value = btn.dataset.status || "Ativo";
  document.getElementById("descricao").value = btn.dataset.descricao || "";
  document.getElementById("form-title").innerText = "Editar cargo";
  document.getElementById("btn-salvar").innerText = "Atualizar cargo";
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function limparCargo() {
  document.getElementById("id_cargo_autonomo").value = "";
  document.getElementById("nome_cargo").value = "";
  document.getElementById("status").value = "Ativo";
  document.getElementById("descricao").value = "";
  document.getElementById("form-title").innerText = "Novo cargo";
  document.getElementById("btn-salvar").innerText = "Salvar cargo";
}
</script>

{% endblock %}
'''

write(BASE / "app" / "templates" / "cadastros" / "cargos_autonomos.html", cargos_template)
print("OK - template cargos_autonomos.html criado.")

# ============================================================
# 5. Template Autônomos com select de cargo
# ============================================================

autonomos_path = BASE / "app" / "templates" / "cadastros" / "autonomos.html"
backup(autonomos_path)

autonomos_template = r'''{% extends "base.html" %}

{% block header %}Autônomos{% endblock %}
{% block subtitle %}Cadastre os autônomos e associe o cargo para filtrar na alocação{% endblock %}

{% block header_action %}
<a class="quick-action light" href="/cargos-autonomos">Cargos</a>
<a class="quick-action light" href="/excel/modelo/autonomos">Modelo Excel</a>
<a class="quick-action light" href="/excel/">Importar Excel</a>
{% endblock %}

{% block content %}

<section class="panel mb-6">
  <form method="get" class="flex gap-3">
    <input class="input" name="q" placeholder="Pesquisar por nome, cargo, especialidade ou status" value="{{ q }}">
    <button class="btn-secondary">Pesquisar</button>
  </form>
</section>

<section class="panel mb-6">
  <div class="panel-head">
    <h3>Novo / editar autônomo</h3>
  </div>

  <form method="post" class="form-grid">
    <input type="hidden" name="id_autonomo" id="id_autonomo">

    <div>
      <label class="label">Nome</label>
      <input class="input" name="nome_autonomo" id="nome_autonomo" required>
    </div>

    <div>
      <label class="label">Cargo</label>
      <select class="input" name="id_cargo_autonomo" id="id_cargo_autonomo">
        <option value="">Selecione</option>
        {% for c in cargos_autonomos %}
          <option value="{{ c.id_cargo_autonomo }}">{{ c.nome_cargo }}</option>
        {% endfor %}
      </select>
      <input type="hidden" name="tipo_autonomo" id="tipo_autonomo">
    </div>

    <div>
      <label class="label">CPF</label>
      <input class="input" name="cpf" id="cpf">
    </div>

    <div>
      <label class="label">Telefone</label>
      <input class="input" name="telefone" id="telefone">
    </div>

    <div>
      <label class="label">Email</label>
      <input class="input" name="email" id="email">
    </div>

    <div>
      <label class="label">Especialidade</label>
      <input class="input" name="especialidade" id="especialidade" placeholder="Ex.: motor, suspensão, dados">
    </div>

    <div>
      <label class="label">Data inclusão</label>
      <input class="input" type="date" name="data_inclusao" id="data_inclusao">
    </div>

    <div>
      <label class="label">Status</label>
      <select class="input" name="status_autonomo" id="status_autonomo">
        {% for s in ['Ativo','Inativo','Desligado','Suspenso'] %}
          <option>{{ s }}</option>
        {% endfor %}
      </select>
    </div>

    <div class="span-3">
      <label class="label">Observações</label>
      <textarea class="input" name="observacoes" id="observacoes"></textarea>
    </div>

    <div class="span-3 ux-actions-row">
      <button class="btn-primary">Salvar autônomo</button>
      <a class="btn-muted" href="/cargos-autonomos">Cadastrar cargos</a>
    </div>
  </form>
</section>

<section class="panel">
  <table class="table">
    <thead>
      <tr>
        <th>Autônomo</th>
        <th>Cargo</th>
        <th>Especialidade</th>
        <th>Status</th>
        <th>Ações</th>
      </tr>
    </thead>

    <tbody>
      {% for a in items %}
      <tr>
        <td class="font-bold">{{ a.nome_autonomo }}</td>
        <td>{{ a.tipo_autonomo or '-' }}</td>
        <td>{{ a.especialidade or '-' }}</td>
        <td><span class="badge badge-{{ a.status_autonomo|lower }}">{{ a.status_autonomo }}</span></td>
        <td class="actions">
          <button
            class="btn-muted"
            type="button"
            data-fill='{"id_autonomo":"{{a.id_autonomo}}","nome_autonomo":"{{a.nome_autonomo}}","cpf":"{{a.cpf or ''}}","telefone":"{{a.telefone or ''}}","email":"{{a.email or ''}}","id_cargo_autonomo":"{{a.id_cargo_autonomo or ''}}","tipo_autonomo":"{{a.tipo_autonomo or ''}}","especialidade":"{{a.especialidade or ''}}","data_inclusao":"{{a.data_inclusao}}","status_autonomo":"{{a.status_autonomo}}","observacoes":"{{a.observacoes or ''}}"}'
          >
            Editar
          </button>

          <form method="post" action="/autonomos/{{ a.id_autonomo }}/desligar" class="actions">
            <input class="input" type="date" name="data_saida" required>
            <input class="input" name="motivo" placeholder="Motivo" required>
            <button class="btn-danger">Desligar</button>
          </form>
        </td>
      </tr>
      {% else %}
      <tr>
        <td colspan="5" class="empty">Nenhum autônomo cadastrado.</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</section>

<script>
document.addEventListener("change", function(e) {
  if (e.target && e.target.id === "id_cargo_autonomo") {
    const opt = e.target.selectedOptions[0];
    document.getElementById("tipo_autonomo").value = opt ? opt.textContent.trim() : "";
  }
});
</script>

{% endblock %}
'''

autonomos_path.write_text(autonomos_template, encoding="utf-8")
print("OK - autonomos.html ajustado.")

# ============================================================
# 6. Ajustar alocações: cargo filtra autônomo em ordem alfabética
# ============================================================

def build_alocacao_template(is_wizard=False):
    if is_wizard:
        header = "Nova Alocação Guiada"
        subtitle = "Selecione o cargo para listar apenas os autônomos disponíveis daquele cargo"
    else:
        header = "Nova Alocação"
        subtitle = "Vincule piloto, etapa, categoria, cargo, autônomo e pacote"

    action = "" if is_wizard else """
{% block header_action %}
<a class="quick-action primary" href="/operacao/nova-guiada">Usar Alocação Guiada</a>
{% endblock %}
"""

    return f'''{{% extends "base.html" %}}

{{% block header %}}{header}{{% endblock %}}
{{% block subtitle %}}{subtitle}{{% endblock %}}
{action}

{{% block content %}}

<div class="ux-help mb-6">
  Primeiro selecione o cargo. Depois o campo Autônomo mostrará somente os profissionais daquele cargo, em ordem alfabética.
</div>

<form class="panel form-grid" method="post">

  <div>
    <label class="label">Piloto</label>
    <select class="input" name="id_piloto" required>
      <option value="">Selecione</option>
      {{% for p in pilotos %}}
        <option value="{{{{ p.id_piloto }}}}">{{{{ p.nome_piloto }}}}</option>
      {{% endfor %}}
    </select>
  </div>

  <div>
    <label class="label">Etapa</label>
    <select class="input" name="id_etapa" id="id_etapa_guiada" required>
      <option value="">Selecione</option>
      {{% for e in etapas %}}
        <option value="{{{{ e.id_etapa }}}}">{{{{ e.temporada }}}} - {{{{ e.nome_etapa }}}}</option>
      {{% endfor %}}
    </select>
  </div>

  <div>
    <label class="label">Categoria</label>
    <select class="input" name="id_prova" id="id_prova_guiada" required>
      <option value="">Selecione</option>
      {{% for p in provas %}}
        <option value="{{{{ p.id_prova }}}}" data-etapa="{{{{ p.id_etapa }}}}">{{{{ p.nome_prova }}}}</option>
      {{% endfor %}}
    </select>
  </div>

  <div>
    <label class="label">Cargo do autônomo</label>
    <select class="input" id="filtro_cargo_autonomo" required>
      <option value="">Selecione o cargo</option>
      {{% for c in cargos_autonomos %}}
        <option value="{{{{ c.id_cargo_autonomo }}}}">{{{{ c.nome_cargo }}}}</option>
      {{% endfor %}}
    </select>
  </div>

  <div>
    <label class="label">Autônomo disponível</label>
    <select class="input" name="id_autonomo" id="id_autonomo_filtrado" required disabled>
      <option value="">Selecione primeiro o cargo</option>
      {{% for a in autonomos %}}
        <option
          value="{{{{ a.id_autonomo }}}}"
          data-cargo="{{{{ a.id_cargo_autonomo or '' }}}}"
          data-nome="{{{{ a.nome_autonomo }}}}"
        >
          {{{{ a.nome_autonomo }}}}
        </option>
      {{% endfor %}}
    </select>
  </div>

  <div>
    <label class="label">Valor do pacote</label>
    <input class="input" name="valor_fechado_etapa" placeholder="3300,00">
  </div>

  <div>
    <label class="label">Dias trabalhados</label>
    <input class="input" type="number" min="1" name="dias_trabalhados" placeholder="Ex.: 3">
  </div>

  <div class="span-3">
    <label class="label">Observações</label>
    <textarea class="input" name="observacoes"></textarea>
  </div>

  <div class="span-3 ux-actions-row">
    <a class="btn-muted" href="/alocacoes">Cancelar</a>
    <button class="btn-primary">Salvar Alocação</button>
  </div>

</form>

<script>
(function() {{
  const cargo = document.getElementById("filtro_cargo_autonomo");
  const autonomo = document.getElementById("id_autonomo_filtrado");
  const etapa = document.getElementById("id_etapa_guiada");
  const categoria = document.getElementById("id_prova_guiada");

  function ordenarAutonomos() {{
    const options = Array.from(autonomo.options).filter(o => o.value);
    options.sort((a, b) => (a.dataset.nome || a.textContent).localeCompare((b.dataset.nome || b.textContent), "pt-BR"));

    options.forEach(o => autonomo.appendChild(o));
  }}

  function filtrarAutonomos() {{
    const cargoId = cargo.value;

    autonomo.value = "";

    if (!cargoId) {{
      autonomo.disabled = true;
      autonomo.options[0].textContent = "Selecione primeiro o cargo";
      Array.from(autonomo.options).forEach(opt => {{
        if (opt.value) opt.hidden = true;
      }});
      return;
    }}

    autonomo.disabled = false;
    autonomo.options[0].textContent = "Selecione o autônomo";

    Array.from(autonomo.options).forEach(opt => {{
      if (!opt.value) {{
        opt.hidden = false;
        return;
      }}
      opt.hidden = opt.dataset.cargo !== cargoId;
    }});
  }}

  function filtrarCategorias() {{
    if (!etapa || !categoria) return;

    const etapaId = etapa.value;

    Array.from(categoria.options).forEach(opt => {{
      if (!opt.value) {{
        opt.hidden = false;
        return;
      }}
      opt.hidden = etapaId && opt.dataset.etapa !== etapaId;
    }});

    if (categoria.selectedOptions.length && categoria.selectedOptions[0].hidden) {{
      categoria.value = "";
    }}
  }}

  ordenarAutonomos();
  filtrarAutonomos();
  filtrarCategorias();

  cargo.addEventListener("change", filtrarAutonomos);
  if (etapa) etapa.addEventListener("change", filtrarCategorias);
}})();
</script>

{{% endblock %}}
'''

write(BASE / "app" / "templates" / "alocacoes" / "form.html", build_alocacao_template(False))
write(BASE / "app" / "templates" / "operacao" / "nova_guiada.html", build_alocacao_template(True))

print("OK - formulários de alocação ajustados com filtro por cargo.")

# ============================================================
# 7. Menu base.html: adicionar Cadastro de Cargos
# ============================================================

base_path = BASE / "app" / "templates" / "base.html"
backup(base_path)

base = base_path.read_text(encoding="utf-8")

if "/cargos-autonomos" not in base:
    base = base.replace(
        "('/autonomos','Autônomos'),",
        "('/autonomos','Autônomos'),('/cargos-autonomos','Cargos de Autônomos'),"
    )
    base = base.replace(
        "('/autonomos','Autonomos'),",
        "('/autonomos','Autônomos'),('/cargos-autonomos','Cargos de Autônomos'),"
    )

base_path.write_text(base, encoding="utf-8")
print("OK - menu atualizado.")

# ============================================================
# 8. Teste local de importação
# ============================================================

import sys
vendor = BASE / ".vendor"
if vendor.exists():
    sys.path.insert(0, str(vendor))

from app.main import app

rotas = sorted([getattr(r, "path", "") for r in app.routes])

print("")
print("ROTAS:")
for r in ["/cargos-autonomos", "/autonomos", "/alocacoes/nova", "/operacao/nova-guiada"]:
    print(f" - {r}: {'OK' if r in rotas else 'NÃO ENCONTRADA'}")

print("")
print("PATCH CONCLUÍDO.")
print("Reinicie o servidor e teste:")
print(" - http://127.0.0.1:8000/cargos-autonomos")
print(" - http://127.0.0.1:8000/autonomos")
print(" - http://127.0.0.1:8000/operacao/nova-guiada")
print(" - http://127.0.0.1:8000/alocacoes/nova")
