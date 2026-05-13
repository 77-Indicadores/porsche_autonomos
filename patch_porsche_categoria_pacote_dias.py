from pathlib import Path
import re
import sqlite3

BASE = Path(__file__).resolve().parent

def backup(path):
    if path.exists():
        bkp = path.with_suffix(path.suffix + ".bak_categoria_pacote")
        if not bkp.exists():
            bkp.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")

def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")

# ============================================================
# 1. Banco: adicionar dias_trabalhados na fato
# ============================================================

db_path = BASE / "data" / "app.db"

if db_path.exists():
    conn = sqlite3.connect(db_path)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(fato_piloto_autonomo_prova)").fetchall()]

    if "dias_trabalhados" not in cols:
        conn.execute("ALTER TABLE fato_piloto_autonomo_prova ADD COLUMN dias_trabalhados INTEGER")
        conn.commit()
        print("OK - coluna dias_trabalhados criada no banco.")
    else:
        print("OK - coluna dias_trabalhados já existe.")

    conn.close()
else:
    print("AVISO - data/app.db não encontrado. O banco local não foi alterado.")

# ============================================================
# 2. Model: garantir import Column/Integer/String e campo dias
# ============================================================

models_path = BASE / "app" / "models.py"
backup(models_path)

models = models_path.read_text(encoding="utf-8")

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

if "dias_trabalhados" not in models:
    marker = "valor_fechado_etapa"
    lines = models.splitlines()
    new_lines = []
    inserted = False

    for line in lines:
        new_lines.append(line)

        if marker in line and not inserted:
            indent = line[:len(line) - len(line.lstrip())]
            new_lines.append(f"{indent}dias_trabalhados = Column(Integer)")
            inserted = True

    models = "\n".join(new_lines) + "\n"

models_path.write_text(models, encoding="utf-8")
print("OK - models.py ajustado.")

# ============================================================
# 3. Router alocações: remover função/status/data da experiência
# ============================================================

aloc_path = BASE / "app" / "routers" / "alocacoes.py"
backup(aloc_path)

aloc = aloc_path.read_text(encoding="utf-8")

# Troca o post /alocacoes/nova inteiro
pattern_criar = r'''@router.post\("/alocacoes/nova"\)
def criar\(.*?return redirect_with_message\("/alocacoes", success="Alocacao criada com sucesso\."\)
'''

new_criar = r'''@router.post("/alocacoes/nova")
def criar(
    id_piloto: int = Form(...),
    id_etapa: int = Form(...),
    id_prova: int = Form(...),
    id_autonomo: int = Form(...),
    valor_fechado_etapa: str = Form(""),
    dias_trabalhados: str = Form(""),
    observacoes: str = Form(""),
    db: Session = Depends(get_db),
):
    funcao_autonomo = "Pacote"

    if conflito_ativo(db, id_piloto, id_prova, funcao_autonomo):
        return redirect_with_message("/alocacoes/nova", error="Já existe pacote ativo para este piloto/categoria.")

    valor = parse_money(valor_fechado_etapa)

    dias = None
    if dias_trabalhados:
        try:
            dias = int(dias_trabalhados)
        except Exception:
            return redirect_with_message("/alocacoes/nova", error="Dias trabalhados deve ser um número inteiro.")

        if dias <= 0:
            return redirect_with_message("/alocacoes/nova", error="Dias trabalhados deve ser maior que zero.")

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

    return redirect_with_message("/alocacoes", success="Alocação criada com sucesso.")
'''

aloc = re.sub(pattern_criar, new_criar, aloc, flags=re.DOTALL)

# Ajusta substituição para manter pacote e dias
aloc = aloc.replace(
    "funcao_autonomo=fato.funcao_autonomo,\n        data_inicio_vinculo=data,\n        status_vinculo=\"Ativo\",\n        valor_fechado_etapa=parse_money(valor_fechado_etapa),\n        status_pagamento=fato.status_pagamento,",
    "funcao_autonomo=fato.funcao_autonomo,\n        data_inicio_vinculo=data,\n        status_vinculo=\"Ativo\",\n        valor_fechado_etapa=parse_money(valor_fechado_etapa) if valor_fechado_etapa else fato.valor_fechado_etapa,\n        dias_trabalhados=fato.dias_trabalhados,\n        status_pagamento=None,"
)

# Remove exigência visual de status no custo
pattern_custo = r'''@router.post\("/alocacoes/\{id_fato\}/custo"\)
def custo\(.*?return redirect_with_message\("/alocacoes", success="Custo fechado atualizado\."\)
'''

new_custo = r'''@router.post("/alocacoes/{id_fato}/custo")
def custo(
    id_fato: int,
    valor_fechado_etapa: str = Form(""),
    dias_trabalhados: str = Form(""),
    documento: str = Form(""),
    observacoes: str = Form(""),
    db: Session = Depends(get_db),
):
    fato = db.get(FatoPilotoAutonomoProva, id_fato)

    if not fato:
        return redirect_with_message("/alocacoes", error="Alocação não encontrada.")

    dias = None
    if dias_trabalhados:
        try:
            dias = int(dias_trabalhados)
        except Exception:
            return redirect_with_message(f"/alocacoes/{id_fato}/custo", error="Dias trabalhados deve ser um número inteiro.")

        if dias <= 0:
            return redirect_with_message(f"/alocacoes/{id_fato}/custo", error="Dias trabalhados deve ser maior que zero.")

    fato.valor_fechado_etapa = parse_money(valor_fechado_etapa)
    fato.dias_trabalhados = dias
    fato.status_pagamento = None
    fato.data_pagamento = None
    fato.documento = documento
    fato.observacoes = observacoes

    db.commit()

    return redirect_with_message("/alocacoes", success="Pacote atualizado.")
'''

aloc = re.sub(pattern_custo, new_custo, aloc, flags=re.DOTALL)

aloc_path.write_text(aloc, encoding="utf-8")
print("OK - alocacoes.py ajustado.")

# ============================================================
# 4. Router wizard: nova alocação guiada sem função/status/data
# ============================================================

wizard_path = BASE / "app" / "routers" / "wizard.py"

if wizard_path.exists():
    backup(wizard_path)

    wizard_code = r'''from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import FatoPilotoAutonomoProva
from app.routers.alocacoes import conflito_ativo, options
from app.template_config import templates
from app.utils import flash_from_request, parse_money, redirect_with_message

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
    id_autonomo: int = Form(...),
    valor_fechado_etapa: str = Form(""),
    dias_trabalhados: str = Form(""),
    observacoes: str = Form(""),
    db: Session = Depends(get_db),
):
    funcao_autonomo = "Pacote"

    if conflito_ativo(db, id_piloto, id_prova, funcao_autonomo):
        return redirect_with_message(
            "/operacao/nova-guiada",
            error="Já existe pacote ativo para este piloto/categoria.",
        )

    valor = parse_money(valor_fechado_etapa)

    dias = None
    if dias_trabalhados:
        try:
            dias = int(dias_trabalhados)
        except Exception:
            return redirect_with_message(
                "/operacao/nova-guiada",
                error="Dias trabalhados deve ser um número inteiro.",
            )

        if dias <= 0:
            return redirect_with_message(
                "/operacao/nova-guiada",
                error="Dias trabalhados deve ser maior que zero.",
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

    return redirect_with_message("/alocacoes", success="Alocação guiada criada com sucesso.")
'''

    wizard_path.write_text(wizard_code, encoding="utf-8")
    print("OK - wizard.py ajustado.")

# ============================================================
# 5. Router cadastros: piloto sem equipe/categoria + nomes categoria
# ============================================================

cad_path = BASE / "app" / "routers" / "cadastros.py"
backup(cad_path)

cad = cad_path.read_text(encoding="utf-8")

# Busca de piloto sem equipe/categoria
cad = cad.replace(
    'query = query.filter(or_(DimPiloto.nome_piloto.ilike(like), DimPiloto.equipe.ilike(like), DimPiloto.categoria_atual.ilike(like), DimPiloto.status_piloto.ilike(like)))',
    'query = query.filter(or_(DimPiloto.nome_piloto.ilike(like), DimPiloto.status_piloto.ilike(like)))'
)

# Ao salvar piloto, força campos não usados vazios
cad = cad.replace("piloto.equipe = equipe", 'piloto.equipe = ""')
cad = cad.replace("piloto.categoria_atual = categoria_atual", 'piloto.categoria_atual = ""')

cad = cad.replace('success="Prova cadastrada."', 'success="Categoria cadastrada."')
cad = cad.replace('success="Tipo de prova cadastrado."', 'success="Tipo de categoria cadastrado."')
cad = cad.replace('success="Tipo de prova atualizado."', 'success="Tipo de categoria atualizado."')

cad_path.write_text(cad, encoding="utf-8")
print("OK - cadastros.py ajustado.")

# ============================================================
# 6. Base menu: remover históricos e renomear prova/categoria
# ============================================================

base_path = BASE / "app" / "templates" / "base.html"
backup(base_path)

base = base_path.read_text(encoding="utf-8")

repls = {
    "Provas": "Categorias",
    "Prova": "Categoria",
    "Tipos de Prova": "Tipos de Categoria",
    "Tipo de Prova": "Tipo de Categoria",
    "Histórico por Piloto": "Alocações por Piloto",
    "Historico por Piloto": "Alocações por Piloto",
    "Histórico por Autônomo": "Alocações por Autônomo",
    "Historico por Autonomo": "Alocações por Autônomo",
    "Custo por Prova": "Custo por Categoria",
    "Custo por Prova": "Custo por Categoria",
}

for a, b in repls.items():
    base = base.replace(a, b)

# remove links dos históricos
base = re.sub(r"\('/relatorios/historico-piloto','[^']*'\),?", "", base)
base = re.sub(r"\('/relatorios/historico-autonomo','[^']*'\),?", "", base)

base_path.write_text(base, encoding="utf-8")
print("OK - base.html ajustado.")

# ============================================================
# 7. Tela pilotos sem equipe/categoria/histórico
# ============================================================

pilotos_path = BASE / "app" / "templates" / "cadastros" / "pilotos.html"
backup(pilotos_path)

pilotos_html = r'''{% extends "base.html" %}

{% block header %}Pilotos{% endblock %}
{% block subtitle %}Cadastro único do piloto. Ele será vinculado às categorias nas alocações.{% endblock %}

{% block header_action %}
<a class="quick-action light" href="/excel/modelo/pilotos">Modelo Excel</a>
<a class="quick-action light" href="/excel/">Importar Excel</a>
{% endblock %}

{% block content %}

<section class="panel mb-6">
  <form method="get" class="flex gap-3">
    <input class="input" name="q" placeholder="Pesquisar por nome ou status" value="{{ q }}">
    <button class="btn-secondary">Pesquisar</button>
  </form>
</section>

<section class="panel mb-6">
  <div class="panel-head">
    <h3>Novo / editar piloto</h3>
  </div>

  <form method="post" class="form-grid">
    <input type="hidden" name="id_piloto" id="id_piloto">

    <div>
      <label class="label">Nome</label>
      <input class="input" name="nome_piloto" id="nome_piloto" required>
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
      <label class="label">Data inclusão</label>
      <input class="input" type="date" name="data_inclusao" id="data_inclusao">
    </div>

    <div>
      <label class="label">Status</label>
      <select class="input" name="status_piloto" id="status_piloto">
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
      <button class="btn-primary">Salvar piloto</button>
    </div>
  </form>
</section>

<section class="panel">
  <table class="table">
    <thead>
      <tr>
        <th>Piloto</th>
        <th>CPF</th>
        <th>Telefone</th>
        <th>Status</th>
        <th>Ações</th>
      </tr>
    </thead>

    <tbody>
      {% for p in items %}
      <tr>
        <td class="font-bold">{{ p.nome_piloto }}</td>
        <td>{{ p.cpf or '-' }}</td>
        <td>{{ p.telefone or '-' }}</td>
        <td><span class="badge badge-{{ p.status_piloto|lower }}">{{ p.status_piloto }}</span></td>
        <td class="actions">
          <button
            class="btn-muted"
            type="button"
            data-fill='{"id_piloto":"{{p.id_piloto}}","nome_piloto":"{{p.nome_piloto}}","cpf":"{{p.cpf or ''}}","telefone":"{{p.telefone or ''}}","email":"{{p.email or ''}}","data_inclusao":"{{p.data_inclusao}}","status_piloto":"{{p.status_piloto}}","observacoes":"{{p.observacoes or ''}}"}'
          >
            Editar
          </button>

          <form method="post" action="/pilotos/{{ p.id_piloto }}/desligar" class="actions">
            <input class="input" type="date" name="data_desligamento" required>
            <input class="input" name="motivo" placeholder="Motivo" required>
            <button class="btn-danger">Desligar</button>
          </form>
        </td>
      </tr>
      {% else %}
      <tr>
        <td colspan="5" class="empty">Nenhum piloto.</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</section>

{% endblock %}
'''

pilotos_path.write_text(pilotos_html, encoding="utf-8")
print("OK - pilotos.html ajustado.")

# ============================================================
# 8. Tela categoria antiga provas.html
# ============================================================

provas_path = BASE / "app" / "templates" / "cadastros" / "provas.html"
backup(provas_path)

provas_html = r'''{% extends "base.html" %}

{% block header %}Categorias{% endblock %}
{% block subtitle %}Cadastre as categorias usadas em cada etapa{% endblock %}

{% block header_action %}
<a class="quick-action light" href="/excel/modelo/provas">Modelo Excel</a>
<a class="quick-action light" href="/excel/">Importar Excel</a>
{% endblock %}

{% block content %}

<section class="panel mb-6">
  <div class="panel-head">
    <h3>Nova categoria</h3>
  </div>

  <form method="post" class="form-grid">
    <div>
      <label class="label">Etapa</label>
      <select class="input" name="id_etapa" required>
        {% for e in etapas %}
          <option value="{{ e.id_etapa }}">{{ e.temporada }} - {{ e.nome_etapa }}</option>
        {% endfor %}
      </select>
    </div>

    <div>
      <label class="label">Tipo de categoria</label>
      <select class="input" name="id_tipo_prova" required>
        {% for t in tipos %}
          <option value="{{ t.id_tipo_prova }}">{{ t.nome_tipo_prova }}</option>
        {% endfor %}
      </select>
    </div>

    <div>
      <label class="label">Nome da categoria</label>
      <input class="input" name="nome_prova" required placeholder="Ex.: Sprint Challenge, Carrera Cup, Endurance">
    </div>

    <div>
      <label class="label">Data</label>
      <input class="input" type="date" name="data_prova">
    </div>

    <div>
      <label class="label">Status</label>
      <select class="input" name="status_prova">
        <option>Planejada</option>
        <option>Confirmada</option>
        <option>Realizada</option>
        <option>Cancelada</option>
      </select>
    </div>

    <div class="span-3">
      <label class="label">Observações</label>
      <textarea class="input" name="observacoes"></textarea>
    </div>

    <div class="span-3">
      <button class="btn-primary">Salvar categoria</button>
    </div>
  </form>
</section>

<section class="panel">
  <table class="table">
    <thead>
      <tr>
        <th>Categoria</th>
        <th>Tipo</th>
        <th>Etapa</th>
        <th>Data</th>
        <th>Status</th>
      </tr>
    </thead>

    <tbody>
      {% for i in items %}
      <tr>
        <td class="font-bold">{{ i.nome_prova }}</td>
        <td>{{ i.tipo_prova.nome_tipo_prova if i.tipo_prova else '-' }}</td>
        <td>{{ i.etapa.nome_etapa if i.etapa else '-' }}</td>
        <td>{{ i.data_prova|date_br }}</td>
        <td>{{ i.status_prova }}</td>
      </tr>
      {% else %}
      <tr>
        <td colspan="5" class="empty">Nenhuma categoria cadastrada.</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</section>

{% endblock %}
'''

provas_path.write_text(provas_html, encoding="utf-8")
print("OK - provas.html renomeado visualmente para categorias.")

# ============================================================
# 9. Tela tipos: tipo de categoria
# ============================================================

tipos_path = BASE / "app" / "templates" / "cadastros" / "tipos.html"
backup(tipos_path)

tipos_html = tipos_path.read_text(encoding="utf-8") if tipos_path.exists() else ""

tipos_html = tipos_html.replace("Tipos de Prova", "Tipos de Categoria")
tipos_html = tipos_html.replace("tipo de prova", "tipo de categoria")
tipos_html = tipos_html.replace("Tipo de prova", "Tipo de categoria")
tipos_html = tipos_html.replace("Salvar tipo", "Salvar tipo")
tipos_html = tipos_html.replace("Atualizar tipo", "Atualizar tipo")

tipos_path.write_text(tipos_html, encoding="utf-8")
print("OK - tipos.html renomeado.")

# ============================================================
# 10. Alocação form/list/custo/wizard templates
# ============================================================

form_path = BASE / "app" / "templates" / "alocacoes" / "form.html"
backup(form_path)

form_html = r'''{% extends "base.html" %}

{% block header %}Nova Alocação{% endblock %}
{% block subtitle %}Vincule piloto, etapa, categoria, autônomo e pacote{% endblock %}

{% block header_action %}
<a class="quick-action primary" href="/operacao/nova-guiada">Usar Alocação Guiada</a>
{% endblock %}

{% block content %}

<form class="panel form-grid" method="post">

  <div>
    <label class="label">Piloto</label>
    <select class="input" name="id_piloto" required>
      <option value="">Selecione</option>
      {% for p in pilotos %}
        <option value="{{ p.id_piloto }}">{{ p.nome_piloto }}</option>
      {% endfor %}
    </select>
  </div>

  <div>
    <label class="label">Etapa</label>
    <select class="input" name="id_etapa" required>
      <option value="">Selecione</option>
      {% for e in etapas %}
        <option value="{{ e.id_etapa }}">{{ e.temporada }} - {{ e.nome_etapa }}</option>
      {% endfor %}
    </select>
  </div>

  <div>
    <label class="label">Categoria</label>
    <select class="input" name="id_prova" required>
      <option value="">Selecione</option>
      {% for p in provas %}
        <option value="{{ p.id_prova }}">{{ p.nome_prova }}</option>
      {% endfor %}
    </select>
  </div>

  <div>
    <label class="label">Autônomo</label>
    <select class="input" name="id_autonomo" required>
      <option value="">Selecione</option>
      {% for a in autonomos %}
        <option value="{{ a.id_autonomo }}">{{ a.nome_autonomo }} - {{ a.tipo_autonomo }}</option>
      {% endfor %}
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
    <button class="btn-primary">Criar alocação</button>
  </div>

</form>

{% endblock %}
'''

form_path.write_text(form_html, encoding="utf-8")
print("OK - alocacoes/form.html ajustado.")

list_path = BASE / "app" / "templates" / "alocacoes" / "list.html"
backup(list_path)

list_html = r'''{% extends "base.html" %}

{% block header %}Gestão de Alocação{% endblock %}
{% block subtitle %}Piloto, categoria, autônomo, pacote, dias trabalhados e valor dia{% endblock %}

{% block header_action %}
<a class="quick-action primary" href="/operacao/nova-guiada">Nova Alocação Guiada</a>
<a class="quick-action light" href="/excel/modelo/alocacoes">Modelo Excel</a>
{% endblock %}

{% block content %}

<section class="ux-grid ux-grid-4 mb-6">
  <div class="ux-card">
    <div class="ux-muted">Alocações listadas</div>
    <div class="ux-kpi">{{ fatos|length }}</div>
  </div>

  <div class="ux-card">
    <div class="ux-muted">Ativas</div>
    <div class="ux-kpi">{{ fatos|selectattr("status_vinculo", "equalto", "Ativo")|list|length }}</div>
  </div>

  <div class="ux-card">
    <div class="ux-muted">Substituídas</div>
    <div class="ux-kpi">{{ fatos|selectattr("status_vinculo", "equalto", "Substituido")|list|length }}</div>
  </div>

  <div class="ux-card">
    <div class="ux-muted">Encerradas</div>
    <div class="ux-kpi">{{ fatos|selectattr("status_vinculo", "equalto", "Encerrado")|list|length }}</div>
  </div>
</section>

<section class="panel mb-6">
  <div class="panel-head">
    <h3>Filtros</h3>
    <div class="ux-actions-row">
      <a class="btn-muted" href="/excel/">Importar Excel</a>
      <a class="btn-muted" href="/setup">Setup Inicial</a>
    </div>
  </div>

  <form method="get" class="grid gap-3 md:grid-cols-4">
    <select class="input" name="id_etapa">
      <option value="">Todas etapas</option>
      {% for e in etapas %}
        <option value="{{ e.id_etapa }}" {% if filtros.id_etapa|string == e.id_etapa|string %}selected{% endif %}>
          {{ e.nome_etapa }}
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

    <select class="input" name="status">
      <option value="">Todos status</option>
      {% for s in ['Ativo','Substituido','Encerrado','Cancelado'] %}
        <option {% if filtros.status == s %}selected{% endif %}>{{ s }}</option>
      {% endfor %}
    </select>

    <button class="btn-secondary">Filtrar</button>
  </form>
</section>

<section class="ux-table-card">
  <div class="overflow-x-auto">
    <table class="table">
      <thead>
        <tr>
          <th>Piloto</th>
          <th>Etapa / Categoria</th>
          <th>Autônomo</th>
          <th>Status</th>
          <th>Valor pacote</th>
          <th>Dias trabalhados</th>
          <th>Valor dia</th>
          <th>Avaliação externa</th>
          <th>Ações</th>
        </tr>
      </thead>

      <tbody>
      {% for f in fatos %}
        {% set valor_dia = (f.valor_fechado_etapa / f.dias_trabalhados) if f.valor_fechado_etapa and f.dias_trabalhados else None %}
        <tr>
          <td>
            <div class="ux-row-main">{{ f.piloto.nome_piloto }}</div>
          </td>

          <td>
            <div class="font-bold">{{ f.etapa.nome_etapa }}</div>
            <div class="ux-muted">{{ f.prova.nome_prova }}</div>
          </td>

          <td>
            <div class="font-bold">{{ f.autonomo.nome_autonomo }}</div>
            <div class="ux-muted">{{ f.autonomo.tipo_autonomo }}</div>
          </td>

          <td>
            {% if f.status_vinculo == 'Ativo' %}
              <span class="ux-pill green">{{ f.status_vinculo }}</span>
            {% elif f.status_vinculo == 'Substituido' %}
              <span class="ux-pill yellow">{{ f.status_vinculo }}</span>
            {% else %}
              <span class="ux-pill red">{{ f.status_vinculo }}</span>
            {% endif %}
          </td>

          <td>{{ f.valor_fechado_etapa|money_br }}</td>

          <td>{{ f.dias_trabalhados or '-' }}</td>

          <td>
            {% if valor_dia %}
              {{ valor_dia|money_br }}
            {% else %}
              -
            {% endif %}
          </td>

          <td>
            {% if f.link_avaliacao_externa %}
              <a class="ux-pill green" href="{{ f.link_avaliacao_externa }}" target="_blank">Abrir link</a>
            {% else %}
              <span class="ux-pill yellow">Sem link</span>
            {% endif %}
          </td>

          <td>
            <div class="ux-actions-row">
              <a class="btn-muted" href="/alocacoes/{{ f.id_fato }}/substituir">Trocar</a>
              <a class="btn-muted" href="/alocacoes/{{ f.id_fato }}/custo">Pacote</a>
              <a class="btn-muted" href="/alocacoes/{{ f.id_fato }}/link-avaliacao">Link avaliação</a>
            </div>

            {% if f.status_vinculo == 'Ativo' %}
            <details class="mt-2">
              <summary class="text-xs font-bold text-red-700 cursor-pointer">Encerrar</summary>
              <form method="post" action="/alocacoes/{{ f.id_fato }}/encerrar" class="grid gap-2 mt-2">
                <input class="input" type="date" name="data_fim" required>
                <input class="input" name="motivo" placeholder="Motivo">
                <button class="btn-danger">Confirmar</button>
              </form>
            </details>
            {% endif %}
          </td>
        </tr>
      {% else %}
        <tr>
          <td colspan="9" class="empty">
            Nenhuma alocação encontrada. Comece pela <a href="/operacao/nova-guiada">Alocação Guiada</a>.
          </td>
        </tr>
      {% endfor %}
      </tbody>
    </table>
  </div>
</section>

{% endblock %}
'''

list_path.write_text(list_html, encoding="utf-8")
print("OK - alocacoes/list.html ajustado.")

custo_path = BASE / "app" / "templates" / "alocacoes" / "custo.html"
backup(custo_path)

custo_html = r'''{% extends "base.html" %}

{% block header %}Pacote da Alocação{% endblock %}
{% block subtitle %}Informe o valor do pacote, dias trabalhados e o sistema calcula o valor dia{% endblock %}

{% block content %}

<section class="ux-card mb-6">
  <h3 class="ux-card-title">Alocação</h3>
  <p><b>Piloto:</b> {{ fato.piloto.nome_piloto }}</p>
  <p><b>Categoria:</b> {{ fato.prova.nome_prova }}</p>
  <p><b>Autônomo:</b> {{ fato.autonomo.nome_autonomo }}</p>
</section>

<section class="panel">
  <form method="post" class="form-grid">
    <div>
      <label class="label">Valor do pacote</label>
      <input class="input" name="valor_fechado_etapa" value="{{ fato.valor_fechado_etapa or '' }}" placeholder="3300,00">
    </div>

    <div>
      <label class="label">Dias trabalhados</label>
      <input class="input" type="number" min="1" name="dias_trabalhados" value="{{ fato.dias_trabalhados or '' }}" placeholder="Ex.: 3">
    </div>

    <div>
      <label class="label">Documento</label>
      <input class="input" name="documento" value="{{ fato.documento or '' }}" placeholder="NF, recibo ou referência">
    </div>

    <div class="span-3">
      <label class="label">Observações</label>
      <textarea class="input" name="observacoes">{{ fato.observacoes or '' }}</textarea>
    </div>

    <div class="span-3 ux-actions-row">
      <a class="btn-muted" href="/alocacoes">Voltar</a>
      <button class="btn-primary">Salvar pacote</button>
    </div>
  </form>
</section>

{% endblock %}
'''

custo_path.write_text(custo_html, encoding="utf-8")
print("OK - custo.html ajustado.")

wizard_template_path = BASE / "app" / "templates" / "operacao" / "nova_guiada.html"
if wizard_template_path.exists():
    backup(wizard_template_path)

    wizard_html = r'''{% extends "base.html" %}

{% block header %}Nova Alocação Guiada{% endblock %}
{% block subtitle %}Vincule piloto, etapa, categoria, autônomo e pacote{% endblock %}

{% block content %}

<div class="ux-help mb-6">
  O piloto é cadastrado apenas uma vez. Aqui você só vincula o piloto à categoria e ao autônomo responsável.
</div>

<form method="post" class="ux-grid">

  <section class="ux-form-section">
    <h3>1. Etapa e categoria</h3>

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
        <label class="label">Categoria</label>
        <select class="input" name="id_prova" id="id_prova_guiada" required>
          <option value="">Selecione a categoria</option>
          {% for p in provas %}
            <option value="{{ p.id_prova }}" data-etapa="{{ p.id_etapa }}">{{ p.nome_prova }}</option>
          {% endfor %}
        </select>
      </div>
    </div>
  </section>

  <section class="ux-form-section">
    <h3>2. Piloto e autônomo</h3>

    <div class="form-grid">
      <div>
        <label class="label">Piloto</label>
        <select class="input" name="id_piloto" required>
          <option value="">Selecione o piloto</option>
          {% for p in pilotos %}
            <option value="{{ p.id_piloto }}">{{ p.nome_piloto }}</option>
          {% endfor %}
        </select>
      </div>

      <div>
        <label class="label">Autônomo</label>
        <select class="input" name="id_autonomo" required>
          <option value="">Selecione o autônomo</option>
          {% for a in autonomos %}
            <option value="{{ a.id_autonomo }}">{{ a.nome_autonomo }} - {{ a.tipo_autonomo }}</option>
          {% endfor %}
        </select>
      </div>
    </div>
  </section>

  <section class="ux-form-section">
    <h3>3. Pacote</h3>

    <div class="form-grid">
      <div>
        <label class="label">Valor do pacote</label>
        <input class="input" name="valor_fechado_etapa" placeholder="Ex.: 3300,00">
      </div>

      <div>
        <label class="label">Dias trabalhados</label>
        <input class="input" type="number" min="1" name="dias_trabalhados" placeholder="Ex.: 3">
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
  const categoria = document.getElementById("id_prova_guiada");

  if (!etapa || !categoria) return;

  function filtrarCategorias() {
    const etapaId = etapa.value;

    Array.from(categoria.options).forEach(opt => {
      if (!opt.value) {
        opt.hidden = false;
        return;
      }

      opt.hidden = etapaId && opt.dataset.etapa !== etapaId;
    });

    if (categoria.selectedOptions.length && categoria.selectedOptions[0].hidden) {
      categoria.value = "";
    }
  }

  etapa.addEventListener("change", filtrarCategorias);
  filtrarCategorias();
})();
</script>

{% endblock %}
'''

    wizard_template_path.write_text(wizard_html, encoding="utf-8")
    print("OK - nova_guiada.html ajustado.")

# ============================================================
# 11. Relatórios: retirar históricos do menu visual, deixar páginas simples
# ============================================================

for rel in [
    BASE / "app" / "templates" / "relatorios" / "historico_piloto.html",
    BASE / "app" / "templates" / "relatorios" / "historico_autonomo.html",
]:
    if rel.exists():
        backup(rel)
        rel.write_text(r'''{% extends "base.html" %}
{% block header %}Consulta desativada{% endblock %}
{% block subtitle %}Esta consulta não faz parte do escopo atual do sistema{% endblock %}
{% block content %}
<section class="ux-card">
  <h3 class="ux-card-title">Tela removida do fluxo operacional</h3>
  <p class="ux-muted">O sistema não terá histórico separado de piloto ou autônomo. Use a Gestão de Alocação para consultar os vínculos por etapa e categoria.</p>
  <div class="ux-actions-row mt-5">
    <a class="btn-primary" href="/alocacoes">Ir para Gestão de Alocação</a>
  </div>
</section>
{% endblock %}
''', encoding="utf-8")

# ============================================================
# 12. Excel mapping: adicionar dias e renomear labels visuais
# ============================================================

excel_path = BASE / "app" / "routers" / "excel.py"

if excel_path.exists():
    backup(excel_path)
    excel = excel_path.read_text(encoding="utf-8")

    excel = excel.replace('"label": "Provas"', '"label": "Categorias"')
    excel = excel.replace('"label": "Tipos de Prova"', '"label": "Tipos de Categoria"')
    excel = excel.replace('"nome_prova"', '"nome_prova"')
    excel = excel.replace('"funcao_autonomo",\n            "data_inicio_vinculo",', '"dias_trabalhados",')
    excel = excel.replace('"status_pagamento",\n            "data_pagamento",', '')
    excel = excel.replace('"Mecânico",\n            "2026-03-10",', '"3",')
    excel = excel.replace('"Pendente",\n            "",', '')

    excel_path.write_text(excel, encoding="utf-8")
    print("OK - excel.py ajustado parcialmente.")

# ============================================================
# 13. Teste local
# ============================================================

import sys
vendor = BASE / ".vendor"
if vendor.exists():
    sys.path.insert(0, str(vendor))

from app.main import app

rotas = sorted([getattr(r, "path", "") for r in app.routes])

print("")
print("ROTAS PRINCIPAIS:")
for r in ["/pilotos", "/provas", "/tipos-prova", "/alocacoes", "/operacao/nova-guiada"]:
    print(f" - {r}: {'OK' if r in rotas else 'NÃO ENCONTRADA'}")

print("")
print("PATCH CONCLUÍDO.")
print("Reinicie o servidor e teste:")
print(" - http://127.0.0.1:8000/pilotos")
print(" - http://127.0.0.1:8000/tipos-prova")
print(" - http://127.0.0.1:8000/provas")
print(" - http://127.0.0.1:8000/operacao/nova-guiada")
print(" - http://127.0.0.1:8000/alocacoes")
