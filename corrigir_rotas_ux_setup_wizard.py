from pathlib import Path
import re

BASE = Path(__file__).resolve().parent
MAIN = BASE / "app" / "main.py"
ROUTERS = BASE / "app" / "routers"
TEMPLATES = BASE / "app" / "templates"

ROUTERS.mkdir(exist_ok=True)
(TEMPLATES / "operacao").mkdir(parents=True, exist_ok=True)
(TEMPLATES / "setup").mkdir(parents=True, exist_ok=True)

# ============================================================
# 1. Criar router wizard.py
# ============================================================

wizard_code = r'''
from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import FatoPilotoAutonomoProva
from app.routers.alocacoes import conflito_ativo, options
from app.template_config import templates
from app.utils import flash_from_request, parse_date, parse_money, redirect_with_message

router = APIRouter(tags=["wizard"])


@router.get("/operacao/nova-guiada")
def nova_guiada(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        "operacao/nova_guiada.html",
        {
            "request": request,
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
    funcao_autonomo: str = Form(...),
    id_autonomo: int = Form(...),
    data_inicio_vinculo: str = Form(...),
    valor_fechado_etapa: str = Form(""),
    status_pagamento: str = Form(""),
    observacoes: str = Form(""),
    db: Session = Depends(get_db),
):
    if conflito_ativo(db, id_piloto, id_prova, funcao_autonomo):
        return redirect_with_message(
            "/operacao/nova-guiada",
            error="Já existe autônomo ativo nessa função para este piloto/prova.",
        )

    valor = parse_money(valor_fechado_etapa)

    if valor is not None and not status_pagamento:
        return redirect_with_message(
            "/operacao/nova-guiada",
            error="Status de pagamento é obrigatório quando houver valor fechado.",
        )

    fato = FatoPilotoAutonomoProva(
        id_piloto=id_piloto,
        id_autonomo=id_autonomo,
        id_etapa=id_etapa,
        id_prova=id_prova,
        funcao_autonomo=funcao_autonomo,
        data_inicio_vinculo=parse_date(data_inicio_vinculo),
        status_vinculo="Ativo",
        valor_fechado_etapa=valor,
        status_pagamento=status_pagamento or None,
        observacoes=observacoes,
    )

    db.add(fato)
    db.commit()

    return redirect_with_message("/alocacoes", success="Alocação guiada criada com sucesso.")
'''

(ROUTERS / "wizard.py").write_text(wizard_code, encoding="utf-8")


# ============================================================
# 2. Criar router setup.py
# ============================================================

setup_code = r'''
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    DimAutonomo,
    DimEtapa,
    DimMotivoTroca,
    DimPiloto,
    DimProva,
    DimStatusPagamento,
    DimTipoProva,
    FatoPilotoAutonomoProva,
)
from app.template_config import templates
from app.utils import flash_from_request

router = APIRouter(tags=["setup"])


@router.get("/setup")
def setup_home(request: Request, db: Session = Depends(get_db)):
    cards = [
        {"titulo": "Pilotos", "qtd": db.query(DimPiloto).count(), "url": "/pilotos", "excel": "/excel/modelo/pilotos"},
        {"titulo": "Autônomos", "qtd": db.query(DimAutonomo).count(), "url": "/autonomos", "excel": "/excel/modelo/autonomos"},
        {"titulo": "Etapas", "qtd": db.query(DimEtapa).count(), "url": "/etapas", "excel": "/excel/modelo/etapas"},
        {"titulo": "Tipos de Prova", "qtd": db.query(DimTipoProva).count(), "url": "/tipos-prova", "excel": "/excel/modelo/tipos-prova"},
        {"titulo": "Provas", "qtd": db.query(DimProva).count(), "url": "/provas", "excel": "/excel/modelo/provas"},
        {"titulo": "Motivos de Troca", "qtd": db.query(DimMotivoTroca).count(), "url": "/motivos-troca", "excel": "/excel/modelo/motivos-troca"},
        {"titulo": "Status Pagamento", "qtd": db.query(DimStatusPagamento).count(), "url": "/excel/", "excel": "/excel/modelo/status-pagamento"},
        {"titulo": "Alocações", "qtd": db.query(FatoPilotoAutonomoProva).count(), "url": "/alocacoes", "excel": "/excel/modelo/alocacoes"},
    ]

    return templates.TemplateResponse(
        "setup/index.html",
        {
            "request": request,
            "cards": cards,
            **flash_from_request(request),
        },
    )
'''

(ROUTERS / "setup.py").write_text(setup_code, encoding="utf-8")


# ============================================================
# 3. Criar template da alocação guiada
# ============================================================

wizard_template = r'''{% extends "base.html" %}
{% block header %}Nova Alocação Guiada{% endblock %}
{% block subtitle %}Fluxo simples para associar piloto, prova, função, autônomo e custo{% endblock %}

{% block content %}

<div class="ux-help mb-6">
  Use essa tela para criar uma alocação sem navegar por vários cadastros. O custo é sempre fechado por etapa/prova.
</div>

<form method="post" class="ux-grid">

  <section class="ux-form-section">
    <h3>1. Etapa e prova</h3>
    <div class="form-grid">
      <div>
        <label class="label">Etapa</label>
        <select class="input" name="id_etapa" id="id_etapa_guiada" required>
          <option value="">Selecione a etapa</option>
          {% for e in etapas %}
            <option value="{{ e.id_etapa }}">{{ e.temporada }} - {{ e.nome_etapa }}</option>
          {% endfor %}
        </select>
      </div>

      <div>
        <label class="label">Prova</label>
        <select class="input" name="id_prova" id="id_prova_guiada" required>
          <option value="">Selecione a prova</option>
          {% for p in provas %}
            <option value="{{ p.id_prova }}" data-etapa="{{ p.id_etapa }}">{{ p.nome_prova }}</option>
          {% endfor %}
        </select>
      </div>
    </div>
  </section>

  <section class="ux-form-section">
    <h3>2. Piloto e função</h3>
    <div class="form-grid">
      <div>
        <label class="label">Piloto</label>
        <select class="input" name="id_piloto" required>
          <option value="">Selecione o piloto</option>
          {% for p in pilotos %}
            <option value="{{ p.id_piloto }}">{{ p.nome_piloto }}{% if p.equipe %} - {{ p.equipe }}{% endif %}</option>
          {% endfor %}
        </select>
      </div>

      <div>
        <label class="label">Função</label>
        <select class="input" name="funcao_autonomo" required>
          <option value="">Selecione a função</option>
          <option>Mecânico</option>
          <option>Engenheiro</option>
          <option>Preparador</option>
          <option>Outro</option>
        </select>
      </div>
    </div>
  </section>

  <section class="ux-form-section">
    <h3>3. Autônomo e início</h3>
    <div class="form-grid">
      <div>
        <label class="label">Autônomo</label>
        <select class="input" name="id_autonomo" required>
          <option value="">Selecione o autônomo</option>
          {% for a in autonomos %}
            <option value="{{ a.id_autonomo }}">{{ a.nome_autonomo }} - {{ a.tipo_autonomo }}</option>
          {% endfor %}
        </select>
      </div>

      <div>
        <label class="label">Data início</label>
        <input class="input" type="date" name="data_inicio_vinculo" value="{{ today }}" required>
      </div>
    </div>
  </section>

  <section class="ux-form-section">
    <h3>4. Custo fechado</h3>
    <div class="form-grid">
      <div>
        <label class="label">Valor fechado</label>
        <input class="input" name="valor_fechado_etapa" placeholder="Ex.: 3300,00">
      </div>

      <div>
        <label class="label">Status pagamento</label>
        <select class="input" name="status_pagamento">
          <option value="">Sem valor / pendente</option>
          {% for p in pagamentos %}
            <option>{{ p.status_pagamento }}</option>
          {% endfor %}
        </select>
      </div>

      <div class="span-3">
        <label class="label">Observações</label>
        <textarea class="input" name="observacoes"></textarea>
      </div>
    </div>
  </section>

  <section class="ux-card">
    <div class="ux-actions-row">
      <a class="btn-muted" href="/alocacoes">Cancelar</a>
      <button class="btn-primary">Salvar Alocação</button>
    </div>
  </section>

</form>

<script>
(function() {
  const etapa = document.getElementById("id_etapa_guiada");
  const prova = document.getElementById("id_prova_guiada");

  if (!etapa || !prova) return;

  function filtrarProvas() {
    const etapaId = etapa.value;
    Array.from(prova.options).forEach(opt => {
      if (!opt.value) {
        opt.hidden = false;
        return;
      }
      opt.hidden = etapaId && opt.dataset.etapa !== etapaId;
    });

    if (prova.selectedOptions.length && prova.selectedOptions[0].hidden) {
      prova.value = "";
    }
  }

  etapa.addEventListener("change", filtrarProvas);
  filtrarProvas();
})();
</script>

{% endblock %}
'''

(TEMPLATES / "operacao" / "nova_guiada.html").write_text(wizard_template, encoding="utf-8")


# ============================================================
# 4. Criar template setup
# ============================================================

setup_template = r'''{% extends "base.html" %}
{% block header %}Setup Inicial{% endblock %}
{% block subtitle %}Cadastros essenciais para começar a operação{% endblock %}

{% block content %}

<div class="ux-help mb-6">
  Comece por pilotos, autônomos, etapas e provas. Depois use a Alocação Guiada.
</div>

<div class="ux-grid ux-grid-4">
  {% for card in cards %}
  <section class="ux-card">
    <div class="flex items-start justify-between gap-3">
      <div>
        <h3 class="ux-card-title">{{ card.titulo }}</h3>
        <p class="ux-muted">Total cadastrado</p>
      </div>

      {% if card.qtd == 0 %}
        <span class="ux-pill red">Vazio</span>
      {% elif card.qtd < 3 %}
        <span class="ux-pill yellow">Parcial</span>
      {% else %}
        <span class="ux-pill green">OK</span>
      {% endif %}
    </div>

    <div class="mt-5">
      <div class="ux-kpi">{{ card.qtd }}</div>
      <div class="ux-muted">registros</div>
    </div>

    <div class="ux-actions-row mt-5">
      <a class="btn-primary" href="{{ card.url }}">Abrir</a>
      <a class="btn-muted" href="{{ card.excel }}">Excel</a>
    </div>
  </section>
  {% endfor %}
</div>

<section class="ux-card dark mt-6">
  <div class="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
    <div>
      <h3 class="ux-card-title">Pronto para operar?</h3>
      <p class="text-zinc-400">Crie uma alocação sem precisar navegar por várias telas.</p>
    </div>
    <a class="quick-action primary" href="/operacao/nova-guiada">Criar Alocação Guiada</a>
  </div>
</section>

{% endblock %}
'''

(TEMPLATES / "setup" / "index.html").write_text(setup_template, encoding="utf-8")


# ============================================================
# 5. Garantir CSS básico se ainda não existir
# ============================================================

css_path = BASE / "app" / "static" / "css" / "style.css"
css_current = css_path.read_text(encoding="utf-8") if css_path.exists() else ""

css_add = r'''

/* UX Cadastro Guiado */
.ux-grid { display: grid; gap: 1rem; }
.ux-grid-4 { grid-template-columns: repeat(4, minmax(0, 1fr)); }
@media (max-width: 900px) { .ux-grid-4 { grid-template-columns: 1fr; } }

.ux-card {
  background: #fff;
  border: 1px solid #e4e4e7;
  border-radius: 1.25rem;
  padding: 1.15rem;
  box-shadow: 0 18px 40px rgba(15, 23, 42, .06);
}

.ux-card.dark {
  background: #09090b;
  color: #fff;
  border-color: #27272a;
}

.ux-card-title {
  font-size: 1rem;
  font-weight: 900;
  color: #18181b;
  margin-bottom: .35rem;
}

.ux-card.dark .ux-card-title { color: #fff; }

.ux-muted {
  color: #71717a;
  font-size: .9rem;
}

.ux-kpi {
  font-size: 2rem;
  font-weight: 950;
  letter-spacing: -0.04em;
  color: #18181b;
}

.ux-help {
  background: #fff7ed;
  border: 1px solid #fed7aa;
  color: #9a3412;
  padding: .85rem 1rem;
  border-radius: 1rem;
  font-size: .9rem;
}

.ux-form-section {
  border: 1px solid #e4e4e7;
  border-radius: 1.25rem;
  padding: 1rem;
  background: #fff;
}

.ux-form-section h3 {
  font-size: 1rem;
  font-weight: 900;
  color: #18181b;
  margin-bottom: .75rem;
}

.ux-actions-row {
  display: flex;
  gap: .45rem;
  flex-wrap: wrap;
  align-items: center;
}

.ux-pill {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  padding: .28rem .55rem;
  background: #f4f4f5;
  color: #27272a;
  font-size: .75rem;
  font-weight: 800;
}

.ux-pill.red { background: #fee2e2; color: #991b1b; }
.ux-pill.green { background: #dcfce7; color: #166534; }
.ux-pill.yellow { background: #fef9c3; color: #854d0e; }

.quick-action {
  display: inline-flex;
  align-items: center;
  gap: .45rem;
  border-radius: 999px;
  padding: .65rem .95rem;
  font-weight: 800;
  font-size: .85rem;
  background: #18181b;
  color: #fff;
  text-decoration: none;
  border: 1px solid rgba(255,255,255,.08);
}

.quick-action.primary { background: #dc2626; }
.quick-action.light { background: #fff; color: #18181b; border: 1px solid #e4e4e7; }
'''

if "UX Cadastro Guiado" not in css_current:
    css_path.write_text(css_current + css_add, encoding="utf-8")


# ============================================================
# 6. Registrar routers no main.py via importlib
# ============================================================

main_path = BASE / "app" / "main.py"
main = main_path.read_text(encoding="utf-8")

backup = main_path.with_suffix(".py.bak_ux_routes")
if not backup.exists():
    backup.write_text(main, encoding="utf-8")

# Remove bloco antigo quebrado de UX se existir
main = re.sub(
    r"\n# ============================================================\n# Rotas de UX: Setup Inicial e Alocação Guiada.*?(?=\n# ============================================================|\Z)",
    "\n",
    main,
    flags=re.DOTALL,
)

ux_block = r'''

# ============================================================
# Rotas UX: Setup Inicial e Alocação Guiada
# ============================================================
try:
    import importlib

    setup_runtime = importlib.import_module("app.routers.setup")
    wizard_runtime = importlib.import_module("app.routers.wizard")

    app.include_router(setup_runtime.router)
    app.include_router(wizard_runtime.router)

    print("OK - Rotas UX registradas: /setup e /operacao/nova-guiada")

except Exception as exc:
    import traceback
    print("ERRO AO REGISTRAR ROTAS UX")
    print(exc)
    print(traceback.format_exc())

    try:
        from app.logging_utils import log_error
        log_error("ERRO_AO_REGISTRAR_ROTAS_UX", exc, {}, excel=False)
    except Exception:
        pass
'''

main = main.rstrip() + ux_block + "\n"
main_path.write_text(main, encoding="utf-8")


# ============================================================
# 7. Teste local
# ============================================================

import sys
vendor = BASE / ".vendor"
if vendor.exists():
    sys.path.insert(0, str(vendor))

from app.main import app

rotas = sorted([getattr(r, "path", "") for r in app.routes])
print("ROTAS UX ENCONTRADAS:")
for r in rotas:
    if r.startswith("/setup") or r.startswith("/operacao"):
        print(" -", r)

if "/operacao/nova-guiada" not in rotas:
    raise SystemExit("ERRO: /operacao/nova-guiada ainda não foi registrada.")

if "/setup" not in rotas:
    raise SystemExit("ERRO: /setup ainda não foi registrada.")

print("OK FINAL - Rotas UX disponíveis.")
