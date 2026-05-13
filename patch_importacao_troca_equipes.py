from pathlib import Path
import re
import sqlite3

BASE = Path(__file__).resolve().parent

def backup(path):
    if path.exists():
        bkp = path.with_suffix(path.suffix + ".bak_import_troca_equipe")
        if not bkp.exists():
            bkp.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")

def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")

# ============================================================
# 1. Banco: garantir colunas novas
# ============================================================

db_path = BASE / "data" / "app.db"

if db_path.exists():
    conn = sqlite3.connect(db_path)

    def cols(table):
        return [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]

    if "foto_url" not in cols("dim_pilotos"):
        conn.execute("ALTER TABLE dim_pilotos ADD COLUMN foto_url TEXT")

    if "dias_trabalhados" not in cols("fato_piloto_autonomo_prova"):
        conn.execute("ALTER TABLE fato_piloto_autonomo_prova ADD COLUMN dias_trabalhados INTEGER")

    if "link_avaliacao_externa" not in cols("fato_piloto_autonomo_prova"):
        conn.execute("ALTER TABLE fato_piloto_autonomo_prova ADD COLUMN link_avaliacao_externa TEXT")

    conn.commit()
    conn.close()

    print("OK - Banco ajustado.")
else:
    print("AVISO - data/app.db não encontrado.")


# ============================================================
# 2. Models: garantir campos
# ============================================================

models_path = BASE / "app" / "models.py"
backup(models_path)

models = models_path.read_text(encoding="utf-8")

if "from sqlalchemy import" in models:
    lines = models.splitlines()
    out = []

    for line in lines:
        if line.startswith("from sqlalchemy import"):
            imports = line.replace("from sqlalchemy import", "").strip()
            parts = [p.strip() for p in imports.split(",") if p.strip()]
            for item in ["Column", "Integer", "String"]:
                if item not in parts:
                    parts.append(item)
            line = "from sqlalchemy import " + ", ".join(parts)
        out.append(line)

    models = "\n".join(out) + "\n"
else:
    models = "from sqlalchemy import Column, Integer, String\n" + models

# foto_url em DimPiloto
if "foto_url" not in models:
    lines = models.splitlines()
    out = []
    inserted = False
    in_piloto = False

    for line in lines:
        if line.startswith("class DimPiloto"):
            in_piloto = True

        out.append(line)

        if in_piloto and not inserted and "observacoes" in line:
            indent = line[:len(line) - len(line.lstrip())]
            out.append(f"{indent}foto_url = Column(String)")
            inserted = True

        if in_piloto and line.startswith("class ") and not line.startswith("class DimPiloto"):
            in_piloto = False

    models = "\n".join(out) + "\n"

# dias_trabalhados e link_avaliacao_externa em Fato
if "dias_trabalhados" not in models:
    models = models.replace(
        "valor_fechado_etapa",
        "valor_fechado_etapa\n    dias_trabalhados = Column(Integer)",
        1
    )

if "link_avaliacao_externa" not in models:
    marker = "comentario_avaliacao"
    lines = models.splitlines()
    out = []
    inserted = False

    for line in lines:
        out.append(line)
        if marker in line and not inserted:
            indent = line[:len(line) - len(line.lstrip())]
            out.append(f"{indent}link_avaliacao_externa = Column(String)")
            inserted = True

    models = "\n".join(out) + "\n"

models_path.write_text(models, encoding="utf-8")
print("OK - models.py ajustado.")


# ============================================================
# 3. cadastros.py: piloto sem equipe/categoria e com foto
# ============================================================

cad_path = BASE / "app" / "routers" / "cadastros.py"
backup(cad_path)

cad = cad_path.read_text(encoding="utf-8")

if "foto_url: str = Form" not in cad:
    cad = cad.replace(
        'observacoes: str = Form(""),\n    db: Session = Depends(get_db),',
        'observacoes: str = Form(""),\n    foto_url: str = Form(""),\n    db: Session = Depends(get_db),',
        1
    )

if "piloto.foto_url" not in cad:
    cad = cad.replace(
        "piloto.observacoes = observacoes",
        'piloto.observacoes = observacoes\n    piloto.foto_url = foto_url'
    )

cad = cad.replace("piloto.equipe = equipe", 'piloto.equipe = ""')
cad = cad.replace("piloto.categoria_atual = categoria_atual", 'piloto.categoria_atual = ""')

cad_path.write_text(cad, encoding="utf-8")
print("OK - cadastros.py ajustado.")


# ============================================================
# 4. alocacoes.py: formar equipe ou substituição
# ============================================================

aloc_path = BASE / "app" / "routers" / "alocacoes.py"
backup(aloc_path)

aloc = aloc_path.read_text(encoding="utf-8")

# garante import cargo
if "DimCargoAutonomo" not in aloc:
    aloc = aloc.replace(
        "from app.models import ",
        "from app.models import DimCargoAutonomo, "
    )

# options com cargos
if '"cargos_autonomos"' not in aloc:
    aloc = aloc.replace(
        '"pagamentos": db.query(DimStatusPagamento).order_by(DimStatusPagamento.id_status_pagamento).all(),',
        '"pagamentos": db.query(DimStatusPagamento).order_by(DimStatusPagamento.id_status_pagamento).all(),\n        "cargos_autonomos": db.query(DimCargoAutonomo).filter(DimCargoAutonomo.status == "Ativo").order_by(DimCargoAutonomo.nome_cargo).all(),'
    )

# substitui função criar
pattern_criar = r'@router.post\("/alocacoes/nova"\)\ndef criar\(.*?return redirect_with_message\("/alocacoes", success=.*?\)\n'
new_criar = r'''@router.post("/alocacoes/nova")
def criar(
    id_piloto: int = Form(...),
    id_etapa: int = Form(...),
    id_prova: int = Form(...),
    id_cargo_autonomo: int = Form(...),
    id_autonomo: int = Form(...),
    tipo_alocacao: str = Form("Formar equipe"),
    id_fato_substituido: str = Form(""),
    id_motivo_troca: str = Form(""),
    justificativa_troca: str = Form(""),
    valor_fechado_etapa: str = Form(""),
    dias_trabalhados: str = Form(""),
    observacoes: str = Form(""),
    db: Session = Depends(get_db),
):
    cargo = db.get(DimCargoAutonomo, id_cargo_autonomo)

    if not cargo:
        return redirect_with_message("/alocacoes/nova", error="Cargo não encontrado.")

    funcao_autonomo = cargo.nome_cargo
    valor = parse_money(valor_fechado_etapa)

    dias = None
    if dias_trabalhados:
        try:
            dias = int(dias_trabalhados)
        except Exception:
            return redirect_with_message("/alocacoes/nova", error="Dias trabalhados deve ser número inteiro.")

        if dias <= 0:
            return redirect_with_message("/alocacoes/nova", error="Dias trabalhados deve ser maior que zero.")

    if tipo_alocacao == "Substituição":
        if not id_fato_substituido:
            return redirect_with_message("/alocacoes/nova", error="Informe quem será substituído.")

        if not id_motivo_troca:
            return redirect_with_message("/alocacoes/nova", error="Informe o motivo da troca.")

        anterior = db.get(FatoPilotoAutonomoProva, int(id_fato_substituido))

        if not anterior:
            return redirect_with_message("/alocacoes/nova", error="Alocação anterior não encontrada.")

        data_troca = date.today()

        anterior.status_vinculo = "Substituido"
        anterior.foi_substituido = "Sim"
        anterior.id_autonomo_substituto = id_autonomo
        anterior.data_troca = data_troca
        anterior.data_fim_vinculo = data_troca
        anterior.id_motivo_troca = int(id_motivo_troca)
        anterior.justificativa_troca = justificativa_troca

    else:
        conflito = conflito_ativo(db, id_piloto, id_prova, funcao_autonomo)

        if conflito:
            return redirect_with_message(
                "/alocacoes/nova",
                error="Já existe autônomo ativo para este piloto, categoria e cargo. Use substituição.",
            )

    fato = FatoPilotoAutonomoProva(
        id_piloto=id_piloto,
        id_autonomo=id_autonomo,
        id_etapa=id_etapa,
        id_prova=id_prova,
        funcao_autonomo=funcao_autonomo,
        data_inicio_vinculo=date.today(),
        status_vinculo="Ativo",
        valor_fechado_etapa=valor,
        dias_trabalhados=dias,
        status_pagamento=None,
        observacoes=observacoes,
    )

    db.add(fato)
    db.commit()

    return redirect_with_message("/alocacoes", success="Alocação salva com sucesso.")
'''

aloc = re.sub(pattern_criar, new_criar, aloc, flags=re.DOTALL)

aloc_path.write_text(aloc, encoding="utf-8")
print("OK - alocacoes.py ajustado.")


# ============================================================
# 5. wizard.py com mesma regra
# ============================================================

wizard_path = BASE / "app" / "routers" / "wizard.py"
backup(wizard_path)

wizard = r'''from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import DimCargoAutonomo, FatoPilotoAutonomoProva
from app.routers.alocacoes import conflito_ativo, options
from app.template_config import templates
from app.utils import flash_from_request, parse_money, redirect_with_message

router = APIRouter(tags=["wizard"])


@router.get("/operacao/nova-guiada")
def nova_guiada(request: Request, db: Session = Depends(get_db)):
    ativos = (
        db.query(FatoPilotoAutonomoProva)
        .filter(FatoPilotoAutonomoProva.status_vinculo == "Ativo")
        .order_by(FatoPilotoAutonomoProva.id_fato.desc())
        .all()
    )

    return templates.TemplateResponse(
        "operacao/nova_guiada.html",
        {
            "request": request,
            "ativos": ativos,
            "today": date.today(),
            **options(db),
            **flash_from_request(request),
        },
    )


@router.post("/operacao/nova-guiada")
def criar_guiada(
    id_etapa: int = Form(...),
    id_prova: int = Form(...),
    id_piloto: int = Form(...),
    id_cargo_autonomo: int = Form(...),
    id_autonomo: int = Form(...),
    tipo_alocacao: str = Form("Formar equipe"),
    id_fato_substituido: str = Form(""),
    id_motivo_troca: str = Form(""),
    justificativa_troca: str = Form(""),
    valor_fechado_etapa: str = Form(""),
    dias_trabalhados: str = Form(""),
    observacoes: str = Form(""),
    db: Session = Depends(get_db),
):
    cargo = db.get(DimCargoAutonomo, id_cargo_autonomo)

    if not cargo:
        return redirect_with_message("/operacao/nova-guiada", error="Cargo não encontrado.")

    funcao_autonomo = cargo.nome_cargo
    valor = parse_money(valor_fechado_etapa)

    dias = None
    if dias_trabalhados:
        try:
            dias = int(dias_trabalhados)
        except Exception:
            return redirect_with_message("/operacao/nova-guiada", error="Dias trabalhados deve ser número inteiro.")

        if dias <= 0:
            return redirect_with_message("/operacao/nova-guiada", error="Dias trabalhados deve ser maior que zero.")

    if tipo_alocacao == "Substituição":
        if not id_fato_substituido:
            return redirect_with_message("/operacao/nova-guiada", error="Informe quem será substituído.")

        if not id_motivo_troca:
            return redirect_with_message("/operacao/nova-guiada", error="Informe o motivo da troca.")

        anterior = db.get(FatoPilotoAutonomoProva, int(id_fato_substituido))

        if not anterior:
            return redirect_with_message("/operacao/nova-guiada", error="Alocação anterior não encontrada.")

        data_troca = date.today()

        anterior.status_vinculo = "Substituido"
        anterior.foi_substituido = "Sim"
        anterior.id_autonomo_substituto = id_autonomo
        anterior.data_troca = data_troca
        anterior.data_fim_vinculo = data_troca
        anterior.id_motivo_troca = int(id_motivo_troca)
        anterior.justificativa_troca = justificativa_troca

    else:
        conflito = conflito_ativo(db, id_piloto, id_prova, funcao_autonomo)

        if conflito:
            return redirect_with_message(
                "/operacao/nova-guiada",
                error="Já existe autônomo ativo para este piloto, categoria e cargo. Use substituição.",
            )

    fato = FatoPilotoAutonomoProva(
        id_piloto=id_piloto,
        id_autonomo=id_autonomo,
        id_etapa=id_etapa,
        id_prova=id_prova,
        funcao_autonomo=funcao_autonomo,
        data_inicio_vinculo=date.today(),
        status_vinculo="Ativo",
        valor_fechado_etapa=valor,
        dias_trabalhados=dias,
        status_pagamento=None,
        observacoes=observacoes,
    )

    db.add(fato)
    db.commit()

    return redirect_with_message("/alocacoes", success="Alocação salva com sucesso.")
'''

write(wizard_path, wizard)
print("OK - wizard.py ajustado.")


# ============================================================
# 6. Template alocação guiada
# ============================================================

nova_guiada = r'''{% extends "base.html" %}

{% block header %}Nova Alocação Guiada{% endblock %}
{% block subtitle %}Forme equipe ou registre substituição do autônomo{% endblock %}

{% block content %}

<div class="ux-help mb-6">
  Ao alocar, escolha se está formando a equipe inicial ou substituindo alguém que já estava vinculado ao piloto.
</div>

<form method="post" class="panel form-grid">

  <div>
    <label class="label">Tipo de alocação</label>
    <select class="input" name="tipo_alocacao" id="tipo_alocacao" required>
      <option>Formar equipe</option>
      <option>Substituição</option>
    </select>
  </div>

  <div>
    <label class="label">Etapa</label>
    <select class="input" name="id_etapa" id="id_etapa" required>
      <option value="">Selecione</option>
      {% for e in etapas %}
        <option value="{{ e.id_etapa }}">{{ e.temporada }} - {{ e.nome_etapa }}</option>
      {% endfor %}
    </select>
  </div>

  <div>
    <label class="label">Categoria</label>
    <select class="input" name="id_prova" id="id_prova" required>
      <option value="">Selecione</option>
      {% for p in provas %}
        <option value="{{ p.id_prova }}" data-etapa="{{ p.id_etapa }}">{{ p.nome_prova }}</option>
      {% endfor %}
    </select>
  </div>

  <div>
    <label class="label">Piloto</label>
    <select class="input" name="id_piloto" id="id_piloto" required>
      <option value="">Selecione</option>
      {% for p in pilotos %}
        <option value="{{ p.id_piloto }}">{{ p.nome_piloto }}</option>
      {% endfor %}
    </select>
  </div>

  <div>
    <label class="label">Cargo</label>
    <select class="input" name="id_cargo_autonomo" id="id_cargo_autonomo" required>
      <option value="">Selecione</option>
      {% for c in cargos_autonomos %}
        <option value="{{ c.id_cargo_autonomo }}">{{ c.nome_cargo }}</option>
      {% endfor %}
    </select>
  </div>

  <div>
    <label class="label">Autônomo</label>
    <select class="input" name="id_autonomo" id="id_autonomo" required disabled>
      <option value="">Selecione primeiro o cargo</option>
      {% for a in autonomos %}
        <option value="{{ a.id_autonomo }}" data-cargo="{{ a.id_cargo_autonomo or '' }}" data-nome="{{ a.nome_autonomo }}">
          {{ a.nome_autonomo }}
        </option>
      {% endfor %}
    </select>
  </div>

  <div class="span-3" id="box_substituicao" style="display:none;">
    <div class="ux-form-section">
      <h3>Dados da substituição</h3>

      <div class="form-grid">
        <div>
          <label class="label">Quem será substituído</label>
          <select class="input" name="id_fato_substituido" id="id_fato_substituido">
            <option value="">Selecione</option>
            {% for f in ativos %}
              <option
                value="{{ f.id_fato }}"
                data-piloto="{{ f.id_piloto }}"
                data-prova="{{ f.id_prova }}"
                data-funcao="{{ f.funcao_autonomo }}"
              >
                {{ f.piloto.nome_piloto }} - {{ f.prova.nome_prova }} - {{ f.funcao_autonomo }} - {{ f.autonomo.nome_autonomo }}
              </option>
            {% endfor %}
          </select>
        </div>

        <div>
          <label class="label">Motivo da troca</label>
          <select class="input" name="id_motivo_troca" id="id_motivo_troca">
            <option value="">Selecione</option>
            {% for m in motivos %}
              <option value="{{ m.id_motivo_troca }}">{{ m.motivo_troca }}</option>
            {% endfor %}
          </select>
        </div>

        <div class="span-3">
          <label class="label">Justificativa</label>
          <textarea class="input" name="justificativa_troca"></textarea>
        </div>
      </div>
    </div>
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
(function() {
  const tipo = document.getElementById("tipo_alocacao");
  const boxSub = document.getElementById("box_substituicao");
  const cargo = document.getElementById("id_cargo_autonomo");
  const autonomo = document.getElementById("id_autonomo");
  const etapa = document.getElementById("id_etapa");
  const categoria = document.getElementById("id_prova");

  function toggleSubstituicao() {
    boxSub.style.display = tipo.value === "Substituição" ? "block" : "none";
  }

  function ordenarAutonomos() {
    const options = Array.from(autonomo.options).filter(o => o.value);
    options.sort((a,b) => (a.dataset.nome || a.textContent).localeCompare((b.dataset.nome || b.textContent), "pt-BR"));
    options.forEach(o => autonomo.appendChild(o));
  }

  function filtrarAutonomos() {
    const cargoId = cargo.value;
    autonomo.value = "";

    if (!cargoId) {
      autonomo.disabled = true;
      autonomo.options[0].textContent = "Selecione primeiro o cargo";
      Array.from(autonomo.options).forEach(o => { if (o.value) o.hidden = true; });
      return;
    }

    autonomo.disabled = false;
    autonomo.options[0].textContent = "Selecione o autônomo";

    Array.from(autonomo.options).forEach(o => {
      if (!o.value) return;
      o.hidden = o.dataset.cargo !== cargoId;
    });
  }

  function filtrarCategorias() {
    const etapaId = etapa.value;

    Array.from(categoria.options).forEach(o => {
      if (!o.value) return;
      o.hidden = etapaId && o.dataset.etapa !== etapaId;
    });

    if (categoria.selectedOptions.length && categoria.selectedOptions[0].hidden) {
      categoria.value = "";
    }
  }

  tipo.addEventListener("change", toggleSubstituicao);
  cargo.addEventListener("change", filtrarAutonomos);
  etapa.addEventListener("change", filtrarCategorias);

  ordenarAutonomos();
  filtrarAutonomos();
  filtrarCategorias();
  toggleSubstituicao();
})();
</script>

{% endblock %}
'''

write(BASE / "app" / "templates" / "operacao" / "nova_guiada.html", nova_guiada)
write(BASE / "app" / "templates" / "alocacoes" / "form.html", nova_guiada.replace("Nova Alocação Guiada", "Nova Alocação"))
print("OK - templates de alocação ajustados.")


# ============================================================
# 7. Tela visual de equipes
# ============================================================

equipes_router = r'''from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import DimEtapa, DimPiloto, DimProva, FatoPilotoAutonomoProva
from app.template_config import templates
from app.utils import flash_from_request

router = APIRouter(tags=["equipes"])


@router.get("/equipes")
def equipes(
    request: Request,
    id_etapa: str = "",
    id_prova: str = "",
    db: Session = Depends(get_db),
):
    query = db.query(FatoPilotoAutonomoProva)

    if id_etapa:
        query = query.filter(FatoPilotoAutonomoProva.id_etapa == int(id_etapa))

    if id_prova:
        query = query.filter(FatoPilotoAutonomoProva.id_prova == int(id_prova))

    fatos = query.order_by(FatoPilotoAutonomoProva.id_piloto, FatoPilotoAutonomoProva.status_vinculo).all()

    pilotos_map = {}

    for f in fatos:
        if f.id_piloto not in pilotos_map:
            pilotos_map[f.id_piloto] = {
                "piloto": f.piloto,
                "ativos": [],
                "substituidos": [],
            }

        if f.status_vinculo == "Ativo":
            pilotos_map[f.id_piloto]["ativos"].append(f)
        elif f.status_vinculo == "Substituido":
            pilotos_map[f.id_piloto]["substituidos"].append(f)

    equipes = list(pilotos_map.values())

    etapas = db.query(DimEtapa).order_by(DimEtapa.temporada.desc(), DimEtapa.nome_etapa).all()
    provas = db.query(DimProva).order_by(DimProva.data_prova.desc()).all()

    return templates.TemplateResponse(
        "equipes/index.html",
        {
            "request": request,
            "equipes": equipes,
            "etapas": etapas,
            "provas": provas,
            "filtros": {"id_etapa": id_etapa, "id_prova": id_prova},
            **flash_from_request(request),
        },
    )
'''

write(BASE / "app" / "routers" / "equipes.py", equipes_router)

equipes_template = r'''{% extends "base.html" %}

{% block header %}Equipes por Piloto{% endblock %}
{% block subtitle %}Visualize a equipe por etapa/categoria e as substituições realizadas{% endblock %}

{% block header_action %}
<a class="quick-action primary" href="/operacao/nova-guiada">Nova Alocação</a>
{% endblock %}

{% block content %}

<section class="panel mb-6">
  <div class="panel-head">
    <h3>Filtros</h3>
  </div>

  <form method="get" class="grid gap-3 md:grid-cols-3">
    <select class="input" name="id_etapa">
      <option value="">Todas etapas</option>
      {% for e in etapas %}
        <option value="{{ e.id_etapa }}" {% if filtros.id_etapa|string == e.id_etapa|string %}selected{% endif %}>
          {{ e.temporada }} - {{ e.nome_etapa }}
        </option>
      {% endfor %}
    </select>

    <select class="input" name="id_prova">
      <option value="">Todas categorias</option>
      {% for p in provas %}
        <option value="{{ p.id_prova }}" {% if filtros.id_prova|string == p.id_prova|string %}selected{% endif %}>
          {{ p.nome_prova }}
        </option>
      {% endfor %}
    </select>

    <button class="btn-secondary">Filtrar</button>
  </form>
</section>

<div class="ux-grid ux-grid-3">
  {% for equipe in equipes %}
  <section class="ux-card">
    <div class="flex items-center gap-4 mb-5">
      {% if equipe.piloto.foto_url %}
        <img src="{{ equipe.piloto.foto_url }}" style="width:64px;height:64px;border-radius:999px;object-fit:cover;">
      {% else %}
        <div style="width:64px;height:64px;border-radius:999px;background:#18181b;color:white;display:flex;align-items:center;justify-content:center;font-weight:900;font-size:22px;">
          {{ equipe.piloto.nome_piloto[:1] }}
        </div>
      {% endif %}

      <div>
        <h3 class="ux-card-title">{{ equipe.piloto.nome_piloto }}</h3>
        <p class="ux-muted">{{ equipe.ativos|length }} ativo(s) na equipe</p>
      </div>
    </div>

    <div class="mb-4">
      <h4 class="font-bold mb-2">Equipe atual</h4>

      {% for f in equipe.ativos %}
        {% set valor_dia = (f.valor_fechado_etapa / f.dias_trabalhados) if f.valor_fechado_etapa and f.dias_trabalhados else None %}
        <div class="p-3 mb-2 rounded-xl border border-zinc-200 bg-zinc-50">
          <div class="font-bold">{{ f.funcao_autonomo }}</div>
          <div>{{ f.autonomo.nome_autonomo }}</div>
          <div class="ux-muted">{{ f.prova.nome_prova }}</div>
          <div class="ux-muted">
            Pacote: {{ f.valor_fechado_etapa|money_br }} |
            Dias: {{ f.dias_trabalhados or '-' }} |
            Dia: {% if valor_dia %}{{ valor_dia|money_br }}{% else %}-{% endif %}
          </div>
        </div>
      {% else %}
        <div class="ux-muted">Nenhum ativo.</div>
      {% endfor %}
    </div>

    {% if equipe.substituidos %}
    <div>
      <h4 class="font-bold mb-2">Substituições</h4>

      {% for f in equipe.substituidos %}
        <div class="p-3 mb-2 rounded-xl border border-yellow-200 bg-yellow-50">
          <div class="font-bold">{{ f.funcao_autonomo }}</div>
          <div>Substituído: {{ f.autonomo.nome_autonomo }}</div>
          <div class="ux-muted">
            Data: {{ f.data_troca|date_br }} |
            Motivo: {{ f.motivo_troca.motivo_troca if f.motivo_troca else '-' }}
          </div>
          <div class="ux-muted">{{ f.justificativa_troca or '' }}</div>
        </div>
      {% endfor %}
    </div>
    {% endif %}
  </section>
  {% else %}
  <section class="ux-card">
    <h3 class="ux-card-title">Nenhuma equipe encontrada</h3>
    <p class="ux-muted">Use a alocação guiada para montar as equipes.</p>
  </section>
  {% endfor %}
</div>

{% endblock %}
'''

write(BASE / "app" / "templates" / "equipes" / "index.html", equipes_template)
print("OK - equipes criado.")


# ============================================================
# 8. main.py: registrar equipes
# ============================================================

main_path = BASE / "app" / "main.py"
backup(main_path)

main = main_path.read_text(encoding="utf-8")

if "app.routers.equipes" not in main:
    block = r'''

# ============================================================
# Rota visual de equipes
# ============================================================
try:
    import importlib
    equipes_runtime = importlib.import_module("app.routers.equipes")
    app.include_router(equipes_runtime.router)
    print("OK - Rota /equipes registrada.")
except Exception as exc:
    import traceback
    print("ERRO AO REGISTRAR /equipes")
    print(exc)
    print(traceback.format_exc())
'''
    main = main.rstrip() + block + "\n"

main_path.write_text(main, encoding="utf-8")


# ============================================================
# 9. Menu lateral e importações no menu
# ============================================================

base_path = BASE / "app" / "templates" / "base.html"
backup(base_path)

base = base_path.read_text(encoding="utf-8")

# adiciona equipes na operação
if "/equipes" not in base:
    base = base.replace(
        "('/alocacoes','📋 Gestão de Alocação'),",
        "('/equipes','👥 Equipes por Piloto'),('/alocacoes','📋 Gestão de Alocação'),"
    )
    base = base.replace(
        "('/alocacoes','Gestão de Alocação'),",
        "('/equipes','👥 Equipes por Piloto'),('/alocacoes','📋 Gestão de Alocação'),"
    )

# garante importações em ferramentas
if "/excel/" not in base:
    base = base.replace(
        "('Ferramentas', [",
        "('Ferramentas', [('/excel/','📥 Importações Excel'),"
    )

base_path.write_text(base, encoding="utf-8")
print("OK - menu ajustado.")


# ============================================================
# 10. Excel: reescrever ENTIDADES coerente
# ============================================================

excel_path = BASE / "app" / "routers" / "excel.py"

if excel_path.exists():
    backup(excel_path)
    excel = excel_path.read_text(encoding="utf-8")

    entidades = r'''ENTIDADES = {
    "pilotos": {
        "label": "Pilotos",
        "table": "dim_pilotos",
        "unique": ["cpf"],
        "columns": [
            "nome_piloto",
            "cpf",
            "telefone",
            "email",
            "foto_url",
            "data_inclusao",
            "data_desligamento",
            "motivo_desligamento",
            "status_piloto",
            "observacoes",
        ],
        "example": [
            "Rafael Martins",
            "111.111.111-11",
            "(11) 99999-1001",
            "rafael@email.com",
            "https://link-da-foto.com/foto.jpg",
            "2026-01-10",
            "",
            "",
            "Ativo",
            "Exemplo",
        ],
    },

    "cargos-autonomos": {
        "label": "Cargos de Autônomos",
        "table": "dim_cargos_autonomos",
        "unique": ["nome_cargo"],
        "columns": [
            "nome_cargo",
            "descricao",
            "status",
        ],
        "example": [
            "Mecânico",
            "Profissional responsável pela parte mecânica",
            "Ativo",
        ],
    },

    "autonomos": {
        "label": "Autônomos",
        "table": "dim_autonomos",
        "unique": ["cpf"],
        "columns": [
            "nome_autonomo",
            "cpf",
            "telefone",
            "email",
            "id_cargo_autonomo",
            "tipo_autonomo",
            "especialidade",
            "data_inclusao",
            "data_saida",
            "motivo_saida",
            "status_autonomo",
            "observacoes",
        ],
        "example": [
            "João Silva",
            "555.555.555-55",
            "(11) 98888-1001",
            "joao@email.com",
            "1",
            "Mecânico",
            "Suspensão",
            "2026-01-05",
            "",
            "",
            "Ativo",
            "Exemplo",
        ],
    },

    "etapas": {
        "label": "Etapas",
        "table": "dim_etapas",
        "unique": ["temporada", "nome_etapa"],
        "columns": [
            "temporada",
            "nome_etapa",
            "local",
            "data_inicio",
            "data_fim",
            "status_etapa",
            "observacoes",
        ],
        "example": [
            "2026",
            "Etapa 01 - Interlagos",
            "São Paulo/SP",
            "2026-03-13",
            "2026-03-15",
            "Planejada",
            "Exemplo",
        ],
    },

    "tipos-prova": {
        "label": "Tipos de Categoria",
        "table": "dim_tipos_prova",
        "unique": ["nome_tipo_prova"],
        "columns": [
            "nome_tipo_prova",
            "descricao",
            "status_tipo_prova",
        ],
        "example": [
            "Carrera Cup",
            "Tipo de categoria",
            "Ativo",
        ],
    },

    "provas": {
        "label": "Categorias",
        "table": "dim_provas",
        "unique": ["id_etapa", "id_tipo_prova", "nome_prova"],
        "columns": [
            "id_etapa",
            "id_tipo_prova",
            "nome_prova",
            "data_prova",
            "status_prova",
            "observacoes",
        ],
        "example": [
            "1",
            "1",
            "Sprint Challenge",
            "2026-03-14",
            "Planejada",
            "Exemplo",
        ],
    },

    "motivos-troca": {
        "label": "Motivos de Troca",
        "table": "dim_motivos_troca",
        "unique": ["motivo_troca"],
        "columns": [
            "motivo_troca",
            "descricao",
            "status",
        ],
        "example": [
            "Solicitação do piloto",
            "Troca solicitada pelo piloto",
            "Ativo",
        ],
    },

    "alocacoes": {
        "label": "Alocações",
        "table": "fato_piloto_autonomo_prova",
        "unique": [
            "id_piloto",
            "id_autonomo",
            "id_etapa",
            "id_prova",
            "funcao_autonomo",
        ],
        "columns": [
            "id_piloto",
            "id_autonomo",
            "id_etapa",
            "id_prova",
            "funcao_autonomo",
            "status_vinculo",
            "foi_substituido",
            "id_autonomo_substituto",
            "data_troca",
            "id_motivo_troca",
            "justificativa_troca",
            "valor_fechado_etapa",
            "dias_trabalhados",
            "link_avaliacao_externa",
            "documento",
            "observacoes",
        ],
        "example": [
            "1",
            "1",
            "1",
            "1",
            "Mecânico",
            "Ativo",
            "Não",
            "",
            "",
            "",
            "",
            "3300",
            "3",
            "https://forms.gle/exemplo",
            "NF-001",
            "Exemplo",
        ],
    },
}'''

    excel = re.sub(
        r"ENTIDADES\s*=\s*\{.*?\n\}\n\n\ndef get_conn",
        entidades + "\n\n\ndef get_conn",
        excel,
        flags=re.DOTALL
    )

    excel_path.write_text(excel, encoding="utf-8")
    print("OK - excel.py mapeado com campos atuais.")


# ============================================================
# 11. Mapeamento documentado
# ============================================================

md = r'''# Mapeamento atual de importações

## Pilotos
- nome_piloto
- cpf
- telefone
- email
- foto_url
- data_inclusao
- data_desligamento
- motivo_desligamento
- status_piloto
- observacoes

Removidos:
- equipe
- categoria_atual

## Cargos de Autônomos
- nome_cargo
- descricao
- status

## Autônomos
- nome_autonomo
- cpf
- telefone
- email
- id_cargo_autonomo
- tipo_autonomo
- especialidade
- data_inclusao
- data_saida
- motivo_saida
- status_autonomo
- observacoes

## Etapas
- temporada
- nome_etapa
- local
- data_inicio
- data_fim
- status_etapa
- observacoes

## Tipos de Categoria
- nome_tipo_prova
- descricao
- status_tipo_prova

## Categorias
- id_etapa
- id_tipo_prova
- nome_prova
- data_prova
- status_prova
- observacoes

## Motivos de Troca
- motivo_troca
- descricao
- status

## Alocações
- id_piloto
- id_autonomo
- id_etapa
- id_prova
- funcao_autonomo
- status_vinculo
- foi_substituido
- id_autonomo_substituto
- data_troca
- id_motivo_troca
- justificativa_troca
- valor_fechado_etapa
- dias_trabalhados
- link_avaliacao_externa
- documento
- observacoes
'''

write(BASE / "MAPEAMENTO_IMPORTACAO_ATUAL.md", md)


# ============================================================
# 12. Teste import app
# ============================================================

import sys
vendor = BASE / ".vendor"
if vendor.exists():
    sys.path.insert(0, str(vendor))

from app.main import app

rotas = sorted([getattr(r, "path", "") for r in app.routes])

print("")
print("ROTAS:")
for r in ["/excel/", "/equipes", "/operacao/nova-guiada", "/alocacoes/nova"]:
    print(f" - {r}: {'OK' if r in rotas else 'NÃO ENCONTRADA'}")

print("")
print("PATCH CONCLUÍDO.")
print("Teste:")
print(" - http://127.0.0.1:8000/excel/")
print(" - http://127.0.0.1:8000/operacao/nova-guiada")
print(" - http://127.0.0.1:8000/equipes")
print(" - http://127.0.0.1:8000/alocacoes")
