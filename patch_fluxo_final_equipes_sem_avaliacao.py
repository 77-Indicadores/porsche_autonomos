from pathlib import Path
import re
import sqlite3

BASE = Path(__file__).resolve().parent

def backup(path):
    if path.exists():
        bkp = path.with_suffix(path.suffix + ".bak_fluxo_final")
        if not bkp.exists():
            bkp.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")

def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")

# ============================================================
# 1. Banco: garantir colunas necessárias para substituição/equipe
# ============================================================

db_path = BASE / "data" / "app.db"

if db_path.exists():
    conn = sqlite3.connect(db_path)

    def cols(table):
        return [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]

    fato_cols = cols("fato_piloto_autonomo_prova")

    needed = {
        "funcao_autonomo": "TEXT",
        "data_inicio_vinculo": "TEXT",
        "data_fim_vinculo": "TEXT",
        "status_vinculo": "TEXT",
        "foi_substituido": "TEXT",
        "id_autonomo_substituto": "INTEGER",
        "data_troca": "TEXT",
        "id_motivo_troca": "INTEGER",
        "justificativa_troca": "TEXT",
        "valor_fechado_etapa": "REAL",
        "dias_trabalhados": "INTEGER",
        "documento": "TEXT",
        "observacoes": "TEXT",
    }

    for col, typ in needed.items():
        if col not in fato_cols:
            conn.execute(f"ALTER TABLE fato_piloto_autonomo_prova ADD COLUMN {col} {typ}")
            print(f"OK - coluna criada: {col}")

    conn.commit()
    conn.close()

# ============================================================
# 2. Remover avaliação/link avaliação de alocações.py
# ============================================================

aloc_path = BASE / "app" / "routers" / "alocacoes.py"
backup(aloc_path)

aloc = aloc_path.read_text(encoding="utf-8")

# Remove rotas de link-avaliacao, se existirem
aloc = re.sub(
    r'\n@router\.get\("/alocacoes/\{id_fato\}/link-avaliacao"\).*?(?=\n@router\.|\Z)',
    "\n",
    aloc,
    flags=re.DOTALL
)

aloc = re.sub(
    r'\n@router\.post\("/alocacoes/\{id_fato\}/link-avaliacao"\).*?(?=\n@router\.|\Z)',
    "\n",
    aloc,
    flags=re.DOTALL
)

# Garante DimCargoAutonomo no import
if "DimCargoAutonomo" not in aloc:
    aloc = aloc.replace(
        "from app.models import ",
        "from app.models import DimCargoAutonomo, "
    )

# Garante cargos no options()
if '"cargos_autonomos"' not in aloc:
    aloc = aloc.replace(
        '"pagamentos": db.query(DimStatusPagamento).order_by(DimStatusPagamento.id_status_pagamento).all(),',
        '"pagamentos": db.query(DimStatusPagamento).order_by(DimStatusPagamento.id_status_pagamento).all(),\n        "cargos_autonomos": db.query(DimCargoAutonomo).filter(DimCargoAutonomo.status == "Ativo").order_by(DimCargoAutonomo.nome_cargo).all(),'
    )

# Reescreve POST de nova alocação para fluxo final
pattern_criar = r'@router\.post\("/alocacoes/nova"\)\ndef criar\(.*?return redirect_with_message\("/alocacoes", success=.*?\)\n'

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
                error="Já existe autônomo ativo para este piloto, categoria e cargo. Use Substituição.",
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
# 3. Nova Alocação: tela final com Formar equipe/Substituição
# ============================================================

form_html = r'''{% extends "base.html" %}

{% block header %}Nova Alocação{% endblock %}
{% block subtitle %}Monte equipe ou registre substituição de autônomo{% endblock %}

{% block content %}

<div class="ux-help mb-6">
  Escolha se esta alocação é para montar a equipe inicial ou para substituir alguém já alocado.
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
          <textarea class="input" name="justificativa_troca" placeholder="Explique o motivo da substituição"></textarea>
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

write(BASE / "app" / "templates" / "alocacoes" / "form.html", form_html)
write(BASE / "app" / "templates" / "operacao" / "nova_guiada.html", form_html.replace("Nova Alocação", "Nova Alocação Guiada", 1))

print("OK - telas de nova alocação ajustadas.")

# ============================================================
# 4. Gestão de Alocação: remover avaliação/link avaliação
# ============================================================

list_path = BASE / "app" / "templates" / "alocacoes" / "list.html"
backup(list_path)

list_html = list_path.read_text(encoding="utf-8")

# Remove botões e colunas antigas
list_html = list_html.replace('<a class="btn-muted" href="/alocacoes/{{ f.id_fato }}/link-avaliacao">Link avaliação</a>', "")
list_html = list_html.replace('<a class="btn-muted" href="/alocacoes/{{ f.id_fato }}/avaliar">Avaliar</a>', "")
list_html = list_html.replace("<th>Avaliação externa</th>", "")
list_html = list_html.replace("<th>Avaliação</th>", "")
list_html = re.sub(
    r"<td>\s*\{% if f\.link_avaliacao_externa %\}.*?\{% endif %\}\s*</td>",
    "",
    list_html,
    flags=re.DOTALL
)
list_html = list_html.replace("colspan=\"9\"", "colspan=\"8\"")

list_path.write_text(list_html, encoding="utf-8")
print("OK - Gestão de Alocação sem avaliação.")

# ============================================================
# 5. Criar/garantir rota Equipes Alocadas
# ============================================================

equipes_router = r'''from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import DimEtapa, DimProva, FatoPilotoAutonomoProva
from app.template_config import templates
from app.utils import flash_from_request

router = APIRouter(tags=["equipes"])


@router.get("/equipes")
def equipes(request: Request, id_etapa: str = "", id_prova: str = "", db: Session = Depends(get_db)):
    query = db.query(FatoPilotoAutonomoProva)

    if id_etapa:
        query = query.filter(FatoPilotoAutonomoProva.id_etapa == int(id_etapa))

    if id_prova:
        query = query.filter(FatoPilotoAutonomoProva.id_prova == int(id_prova))

    fatos = query.order_by(
        FatoPilotoAutonomoProva.id_etapa,
        FatoPilotoAutonomoProva.id_prova,
        FatoPilotoAutonomoProva.id_piloto,
        FatoPilotoAutonomoProva.funcao_autonomo,
    ).all()

    grupos = {}

    for f in fatos:
        chave = (f.id_etapa, f.id_prova, f.id_piloto)

        if chave not in grupos:
            grupos[chave] = {
                "etapa": f.etapa,
                "categoria": f.prova,
                "piloto": f.piloto,
                "ativos": [],
                "substituidos": [],
                "valor_total": 0,
                "dias_total": 0,
            }

        if f.status_vinculo == "Ativo":
            grupos[chave]["ativos"].append(f)
            grupos[chave]["valor_total"] += float(f.valor_fechado_etapa or 0)
            grupos[chave]["dias_total"] += int(f.dias_trabalhados or 0)

        elif f.status_vinculo == "Substituido":
            grupos[chave]["substituidos"].append(f)

    return templates.TemplateResponse(
        "equipes/index.html",
        {
            "request": request,
            "equipes": list(grupos.values()),
            "etapas": db.query(DimEtapa).order_by(DimEtapa.temporada.desc(), DimEtapa.nome_etapa).all(),
            "categorias": db.query(DimProva).order_by(DimProva.data_prova.desc()).all(),
            "filtros": {"id_etapa": id_etapa, "id_prova": id_prova},
            **flash_from_request(request),
        },
    )
'''

write(BASE / "app" / "routers" / "equipes.py", equipes_router)

equipes_template = r'''{% extends "base.html" %}

{% block header %}Equipes Alocadas{% endblock %}
{% block subtitle %}Visualize por etapa e categoria a equipe formada para cada piloto{% endblock %}

{% block header_action %}
<a class="quick-action primary" href="/alocacoes/nova">Nova Alocação</a>
<a class="quick-action light" href="/alocacoes">Gestão de Alocação</a>
{% endblock %}

{% block content %}

<section class="panel mb-6">
  <div class="panel-head">
    <div>
      <h3>Filtros</h3>
      <p class="text-sm text-zinc-500">Selecione a etapa e a categoria para visualizar a equipe alocada.</p>
    </div>
  </div>

  <form method="get" class="grid gap-3 md:grid-cols-3">
    <select class="input" name="id_etapa" id="id_etapa_filtro">
      <option value="">Todas as etapas</option>
      {% for e in etapas %}
        <option value="{{ e.id_etapa }}" {% if filtros.id_etapa|string == e.id_etapa|string %}selected{% endif %}>
          {{ e.temporada }} - {{ e.nome_etapa }}
        </option>
      {% endfor %}
    </select>

    <select class="input" name="id_prova" id="id_categoria_filtro">
      <option value="">Todas as categorias</option>
      {% for c in categorias %}
        <option value="{{ c.id_prova }}" data-etapa="{{ c.id_etapa }}" {% if filtros.id_prova|string == c.id_prova|string %}selected{% endif %}>
          {{ c.nome_prova }}
        </option>
      {% endfor %}
    </select>

    <button class="btn-secondary">Filtrar equipes</button>
  </form>
</section>

<div class="ux-grid ux-grid-3">
  {% for equipe in equipes %}
    <section class="ux-card">
      <div class="flex items-start justify-between gap-3 mb-5">
        <div class="flex items-center gap-4">
          <div style="width:64px;height:64px;border-radius:999px;background:#18181b;color:white;display:flex;align-items:center;justify-content:center;font-weight:900;font-size:22px;">
            {{ equipe.piloto.nome_piloto[:1] }}
          </div>

          <div>
            <h3 class="ux-card-title">{{ equipe.piloto.nome_piloto }}</h3>
            <div class="ux-muted">{{ equipe.etapa.nome_etapa }}</div>
            <div class="ux-pill mt-2">{{ equipe.categoria.nome_prova }}</div>
          </div>
        </div>

        {% if equipe.substituidos %}
          <span class="ux-pill yellow">Teve troca</span>
        {% else %}
          <span class="ux-pill green">Equipe formada</span>
        {% endif %}
      </div>

      <div class="grid gap-3">
        {% for f in equipe.ativos %}
          {% set valor_dia = (f.valor_fechado_etapa / f.dias_trabalhados) if f.valor_fechado_etapa and f.dias_trabalhados else None %}

          <div class="p-3 rounded-xl border border-zinc-200 bg-zinc-50">
            <div class="font-black text-zinc-950">{{ f.funcao_autonomo }}</div>
            <div class="font-bold">{{ f.autonomo.nome_autonomo }}</div>
            <div class="ux-muted">{{ f.autonomo.especialidade or '-' }}</div>

            <div class="mt-3 grid grid-cols-3 gap-2 text-sm">
              <div>
                <div class="ux-muted">Pacote</div>
                <div class="font-bold">{{ f.valor_fechado_etapa|money_br }}</div>
              </div>

              <div>
                <div class="ux-muted">Dias</div>
                <div class="font-bold">{{ f.dias_trabalhados or '-' }}</div>
              </div>

              <div>
                <div class="ux-muted">Valor dia</div>
                <div class="font-bold">
                  {% if valor_dia %}
                    {{ valor_dia|money_br }}
                  {% else %}
                    -
                  {% endif %}
                </div>
              </div>
            </div>
          </div>
        {% else %}
          <div class="ux-muted">Nenhum autônomo ativo nessa equipe.</div>
        {% endfor %}
      </div>

      {% if equipe.substituidos %}
        <div class="mt-5">
          <h4 class="font-black mb-2">Substituições</h4>

          {% for f in equipe.substituidos %}
            <div class="p-3 mb-2 rounded-xl border border-yellow-200 bg-yellow-50">
              <div class="font-bold">{{ f.funcao_autonomo }}</div>
              <div>Substituído: <b>{{ f.autonomo.nome_autonomo }}</b></div>

              {% if f.autonomo_substituto %}
                <div>Entrou: <b>{{ f.autonomo_substituto.nome_autonomo }}</b></div>
              {% endif %}

              <div class="ux-muted">
                Data: {{ f.data_troca|date_br }}
                {% if f.motivo_troca %}
                  | Motivo: {{ f.motivo_troca.motivo_troca }}
                {% endif %}
              </div>

              {% if f.justificativa_troca %}
                <div class="ux-muted mt-1">{{ f.justificativa_troca }}</div>
              {% endif %}
            </div>
          {% endfor %}
        </div>
      {% endif %}
    </section>
  {% else %}
    <section class="ux-card">
      <h3 class="ux-card-title">Nenhuma equipe encontrada</h3>
      <p class="ux-muted">Use a Nova Alocação para formar a equipe.</p>
      <div class="ux-actions-row mt-5">
        <a class="btn-primary" href="/alocacoes/nova">Criar Alocação</a>
      </div>
    </section>
  {% endfor %}
</div>

{% endblock %}
'''

write(BASE / "app" / "templates" / "equipes" / "index.html", equipes_template)

print("OK - Equipes Alocadas criada.")

# ============================================================
# 6. main.py: registrar rota equipes
# ============================================================

main_path = BASE / "app" / "main.py"
backup(main_path)

main = main_path.read_text(encoding="utf-8")

if "app.routers.equipes" not in main:
    main += r'''

# ============================================================
# Rota visual: Equipes Alocadas
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

main_path.write_text(main, encoding="utf-8")

# ============================================================
# 7. Menu lateral final
# ============================================================

base_path = BASE / "app" / "templates" / "base.html"
backup(base_path)

base = base_path.read_text(encoding="utf-8")

# Remove menus/links que não serão usados agora
remover = [
    "('/relatorios/trocas','🔁 Trocas'),",
    "('/relatorios/trocas','Trocas'),",
    "('/relatorios/avaliacoes','Avaliações'),",
    "('/relatorios/avaliacoes','Avaliacoes'),",
    "('/relatorios/custos','Custos por Etapa'),",
    "('/relatorios/custos','Relatórios Financeiros'),",
    "('/relatorios/custos','Relatorios Financeiros'),",
    "('/relatorios/custos','Custo por Categoria'),",
    "('/equipes','Equipes por Piloto'),",
    "('/equipes','👥 Equipes por Piloto'),",
    "('/equipes','Equipes Alocadas'),",
    "('/equipes','👥 Equipes Alocadas'),",
]

for item in remover:
    base = base.replace(item, "")

# Remove grupos Financeiro e Relatórios inteiros, se existirem
base = re.sub(r"\s*\('Financeiro',\s*\[.*?\]\),?", "", base, flags=re.DOTALL)
base = re.sub(r"\s*\('Relatórios',\s*\[.*?\]\),?", "", base, flags=re.DOTALL)
base = re.sub(r"\s*\('Relatorios',\s*\[.*?\]\),?", "", base, flags=re.DOTALL)

# Garante Equipes Alocadas no grupo Operação
if "('/equipes','👥 Equipes Alocadas')" not in base:
    if "('/alocacoes','📋 Gestão de Alocação')," in base:
        base = base.replace(
            "('/alocacoes','📋 Gestão de Alocação'),",
            "('/equipes','👥 Equipes Alocadas'),('/alocacoes','📋 Gestão de Alocação'),"
        )
    elif "('/alocacoes','Gestão de Alocação')," in base:
        base = base.replace(
            "('/alocacoes','Gestão de Alocação'),",
            "('/equipes','👥 Equipes Alocadas'),('/alocacoes','Gestão de Alocação'),"
        )
    elif "('Operação', [" in base:
        base = base.replace(
            "('Operação', [",
            "('Operação', [('/equipes','👥 Equipes Alocadas'),"
        )
    elif "('Operacao', [" in base:
        base = base.replace(
            "('Operacao', [",
            "('Operacao', [('/equipes','👥 Equipes Alocadas'),"
        )

base_path.write_text(base, encoding="utf-8")
print("OK - menu lateral final ajustado.")

# ============================================================
# 8. Teste de rotas
# ============================================================

import sys
vendor = BASE / ".vendor"
if vendor.exists():
    sys.path.insert(0, str(vendor))

from app.main import app

rotas = sorted([getattr(r, "path", "") for r in app.routes])

print("")
print("ROTAS:")
for r in ["/equipes", "/alocacoes", "/alocacoes/nova", "/operacao/nova-guiada"]:
    print(f" - {r}: {'OK' if r in rotas else 'NÃO ENCONTRADA'}")

print("")
print("PATCH CONCLUÍDO.")
print("Teste:")
print("http://127.0.0.1:8000/equipes")
print("http://127.0.0.1:8000/alocacoes/nova")
