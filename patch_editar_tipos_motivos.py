from pathlib import Path
import re

BASE = Path(__file__).resolve().parent

def backup(path):
    if path.exists():
        bkp = path.with_suffix(path.suffix + ".bak_edit_tipos_motivos")
        if not bkp.exists():
            bkp.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")

# ============================================================
# 1. Ajustar backend: app/routers/cadastros.py
# ============================================================

cad_path = BASE / "app" / "routers" / "cadastros.py"
backup(cad_path)

cad = cad_path.read_text(encoding="utf-8")

old_tipo = r'''@router.post("/tipos-prova")
def salvar_tipo(nome_tipo_prova: str = Form(...), descricao: str = Form(""), status_tipo_prova: str = Form("Ativo"), db: Session = Depends(get_db)):
    db.add(DimTipoProva(nome_tipo_prova=nome_tipo_prova, descricao=descricao, status_tipo_prova=status_tipo_prova))
    db.commit()
    return redirect_with_message("/tipos-prova", success="Tipo de prova cadastrado.")
'''

new_tipo = r'''@router.post("/tipos-prova")
def salvar_tipo(
    id_tipo_prova: str = Form(""),
    nome_tipo_prova: str = Form(...),
    descricao: str = Form(""),
    status_tipo_prova: str = Form("Ativo"),
    db: Session = Depends(get_db),
):
    tipo = db.get(DimTipoProva, int(id_tipo_prova)) if id_tipo_prova else DimTipoProva()

    if not tipo:
        return redirect_with_message("/tipos-prova", error="Tipo de prova não encontrado.")

    tipo.nome_tipo_prova = nome_tipo_prova
    tipo.descricao = descricao
    tipo.status_tipo_prova = status_tipo_prova

    db.add(tipo)
    db.commit()

    msg = "Tipo de prova atualizado." if id_tipo_prova else "Tipo de prova cadastrado."
    return redirect_with_message("/tipos-prova", success=msg)
'''

old_motivo = r'''@router.post("/motivos-troca")
def salvar_motivo(motivo_troca: str = Form(...), descricao: str = Form(""), status: str = Form("Ativo"), db: Session = Depends(get_db)):
    db.add(DimMotivoTroca(motivo_troca=motivo_troca, descricao=descricao, status=status))
    db.commit()
    return redirect_with_message("/motivos-troca", success="Motivo cadastrado.")
'''

new_motivo = r'''@router.post("/motivos-troca")
def salvar_motivo(
    id_motivo_troca: str = Form(""),
    motivo_troca: str = Form(...),
    descricao: str = Form(""),
    status: str = Form("Ativo"),
    db: Session = Depends(get_db),
):
    motivo = db.get(DimMotivoTroca, int(id_motivo_troca)) if id_motivo_troca else DimMotivoTroca()

    if not motivo:
        return redirect_with_message("/motivos-troca", error="Motivo de troca não encontrado.")

    motivo.motivo_troca = motivo_troca
    motivo.descricao = descricao
    motivo.status = status

    db.add(motivo)
    db.commit()

    msg = "Motivo de troca atualizado." if id_motivo_troca else "Motivo cadastrado."
    return redirect_with_message("/motivos-troca", success=msg)
'''

if old_tipo in cad:
    cad = cad.replace(old_tipo, new_tipo)
else:
    cad = re.sub(
        r'@router\.post\("/tipos-prova"\)\ndef salvar_tipo\(.*?return redirect_with_message\("/tipos-prova".*?\)\n',
        new_tipo,
        cad,
        flags=re.DOTALL
    )

if old_motivo in cad:
    cad = cad.replace(old_motivo, new_motivo)
else:
    cad = re.sub(
        r'@router\.post\("/motivos-troca"\)\ndef salvar_motivo\(.*?return redirect_with_message\("/motivos-troca".*?\)\n',
        new_motivo,
        cad,
        flags=re.DOTALL
    )

cad_path.write_text(cad, encoding="utf-8")
print("OK - Backend atualizado para editar tipos e motivos.")


# ============================================================
# 2. Ajustar tela Tipos de Prova
# ============================================================

tipos_path = BASE / "app" / "templates" / "cadastros" / "tipos.html"
backup(tipos_path)

tipos_html = r'''{% extends "base.html" %}

{% block header %}Tipos de Prova{% endblock %}
{% block subtitle %}Cadastre e edite os tipos de prova usados nas etapas{% endblock %}

{% block header_action %}
<a class="quick-action light" href="/excel/modelo/tipos-prova">Modelo Excel</a>
<a class="quick-action light" href="/excel/">Importar Excel</a>
{% endblock %}

{% block content %}

<section class="panel mb-6">
  <div class="panel-head">
    <div>
      <h3 id="form-title">Novo tipo de prova</h3>
      <p class="text-sm text-zinc-500">Use esta lista para Sprint, Endurance, Carrera Cup ou outros tipos.</p>
    </div>
    <button class="btn-muted" type="button" onclick="limparTipo()">Novo</button>
  </div>

  <form method="post" class="form-grid">
    <input type="hidden" name="id_tipo_prova" id="id_tipo_prova">

    <div>
      <label class="label">Nome</label>
      <input class="input" name="nome_tipo_prova" id="nome_tipo_prova" required>
    </div>

    <div>
      <label class="label">Status</label>
      <select class="input" name="status_tipo_prova" id="status_tipo_prova">
        <option>Ativo</option>
        <option>Inativo</option>
      </select>
    </div>

    <div class="span-3">
      <label class="label">Descrição</label>
      <textarea class="input" name="descricao" id="descricao"></textarea>
    </div>

    <div class="span-3 ux-actions-row">
      <button class="btn-primary" id="btn-salvar">Salvar tipo</button>
      <button class="btn-muted" type="button" onclick="limparTipo()">Limpar</button>
    </div>
  </form>
</section>

<section class="panel">
  <div class="panel-head">
    <h3>Tipos cadastrados</h3>
  </div>

  <div class="overflow-x-auto">
    <table class="table">
      <thead>
        <tr>
          <th>Tipo</th>
          <th>Status</th>
          <th>Descrição</th>
          <th>Ações</th>
        </tr>
      </thead>

      <tbody>
        {% for i in items %}
        <tr>
          <td class="font-bold">{{ i.nome_tipo_prova }}</td>
          <td>{{ i.status_tipo_prova }}</td>
          <td>{{ i.descricao or '-' }}</td>
          <td>
            <button
              class="btn-muted"
              type="button"
              data-id="{{ i.id_tipo_prova }}"
              data-nome="{{ i.nome_tipo_prova }}"
              data-status="{{ i.status_tipo_prova }}"
              data-descricao="{{ i.descricao or '' }}"
              onclick="editarTipo(this)"
            >
              Editar
            </button>
          </td>
        </tr>
        {% else %}
        <tr>
          <td colspan="4" class="empty">Nenhum tipo de prova cadastrado.</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</section>

<script>
function editarTipo(btn) {
  document.getElementById("id_tipo_prova").value = btn.dataset.id || "";
  document.getElementById("nome_tipo_prova").value = btn.dataset.nome || "";
  document.getElementById("status_tipo_prova").value = btn.dataset.status || "Ativo";
  document.getElementById("descricao").value = btn.dataset.descricao || "";
  document.getElementById("form-title").innerText = "Editar tipo de prova";
  document.getElementById("btn-salvar").innerText = "Atualizar tipo";
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function limparTipo() {
  document.getElementById("id_tipo_prova").value = "";
  document.getElementById("nome_tipo_prova").value = "";
  document.getElementById("status_tipo_prova").value = "Ativo";
  document.getElementById("descricao").value = "";
  document.getElementById("form-title").innerText = "Novo tipo de prova";
  document.getElementById("btn-salvar").innerText = "Salvar tipo";
}
</script>

{% endblock %}
'''

tipos_path.write_text(tipos_html, encoding="utf-8")
print("OK - Tela Tipos de Prova atualizada com edição.")


# ============================================================
# 3. Ajustar tela Motivos de Troca
# ============================================================

motivos_path = BASE / "app" / "templates" / "cadastros" / "motivos.html"
backup(motivos_path)

motivos_html = r'''{% extends "base.html" %}

{% block header %}Motivos de Troca{% endblock %}
{% block subtitle %}Cadastre e edite os motivos usados nas substituições de autônomos{% endblock %}

{% block header_action %}
<a class="quick-action light" href="/excel/modelo/motivos-troca">Modelo Excel</a>
<a class="quick-action light" href="/excel/">Importar Excel</a>
{% endblock %}

{% block content %}

<section class="panel mb-6">
  <div class="panel-head">
    <div>
      <h3 id="form-title">Novo motivo de troca</h3>
      <p class="text-sm text-zinc-500">Padronize os motivos para facilitar relatório de trocas.</p>
    </div>
    <button class="btn-muted" type="button" onclick="limparMotivo()">Novo</button>
  </div>

  <form method="post" class="form-grid">
    <input type="hidden" name="id_motivo_troca" id="id_motivo_troca">

    <div>
      <label class="label">Motivo</label>
      <input class="input" name="motivo_troca" id="motivo_troca" required>
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
      <button class="btn-primary" id="btn-salvar">Salvar motivo</button>
      <button class="btn-muted" type="button" onclick="limparMotivo()">Limpar</button>
    </div>
  </form>
</section>

<section class="panel">
  <div class="panel-head">
    <h3>Motivos cadastrados</h3>
  </div>

  <div class="overflow-x-auto">
    <table class="table">
      <thead>
        <tr>
          <th>Motivo</th>
          <th>Status</th>
          <th>Descrição</th>
          <th>Ações</th>
        </tr>
      </thead>

      <tbody>
        {% for i in items %}
        <tr>
          <td class="font-bold">{{ i.motivo_troca }}</td>
          <td>{{ i.status }}</td>
          <td>{{ i.descricao or '-' }}</td>
          <td>
            <button
              class="btn-muted"
              type="button"
              data-id="{{ i.id_motivo_troca }}"
              data-motivo="{{ i.motivo_troca }}"
              data-status="{{ i.status }}"
              data-descricao="{{ i.descricao or '' }}"
              onclick="editarMotivo(this)"
            >
              Editar
            </button>
          </td>
        </tr>
        {% else %}
        <tr>
          <td colspan="4" class="empty">Nenhum motivo cadastrado.</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</section>

<script>
function editarMotivo(btn) {
  document.getElementById("id_motivo_troca").value = btn.dataset.id || "";
  document.getElementById("motivo_troca").value = btn.dataset.motivo || "";
  document.getElementById("status").value = btn.dataset.status || "Ativo";
  document.getElementById("descricao").value = btn.dataset.descricao || "";
  document.getElementById("form-title").innerText = "Editar motivo de troca";
  document.getElementById("btn-salvar").innerText = "Atualizar motivo";
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function limparMotivo() {
  document.getElementById("id_motivo_troca").value = "";
  document.getElementById("motivo_troca").value = "";
  document.getElementById("status").value = "Ativo";
  document.getElementById("descricao").value = "";
  document.getElementById("form-title").innerText = "Novo motivo de troca";
  document.getElementById("btn-salvar").innerText = "Salvar motivo";
}
</script>

{% endblock %}
'''

motivos_path.write_text(motivos_html, encoding="utf-8")
print("OK - Tela Motivos de Troca atualizada com edição.")


# ============================================================
# 4. Teste de importação
# ============================================================

import sys
vendor = BASE / ".vendor"
if vendor.exists():
    sys.path.insert(0, str(vendor))

from app.main import app

rotas = sorted([getattr(r, "path", "") for r in app.routes])
print("")
print("ROTAS PRINCIPAIS:")
for r in rotas:
    if r in ["/tipos-prova", "/motivos-troca", "/alocacoes"]:
        print(" -", r)

print("")
print("PATCH CONCLUÍDO.")
print("Reinicie o servidor e teste:")
print(" - http://127.0.0.1:8000/tipos-prova")
print(" - http://127.0.0.1:8000/motivos-troca")
print(" - http://127.0.0.1:8000/alocacoes")
