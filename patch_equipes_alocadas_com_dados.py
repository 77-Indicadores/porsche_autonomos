from pathlib import Path
import sqlite3
import re

BASE = Path(__file__).resolve().parent

def backup(path):
    if path.exists():
        bkp = path.with_suffix(path.suffix + ".bak_equipes_alocadas")
        if not bkp.exists():
            bkp.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")

def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")

# ============================================================
# 1. Garantir banco com colunas necessárias e dados de exemplo
# ============================================================

db_path = BASE / "data" / "app.db"

if not db_path.exists():
    raise SystemExit("Banco data/app.db não encontrado. Rode o sistema/seed primeiro.")

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

def cols(table):
    return [r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]

# Campos extras
if "foto_url" not in cols("dim_pilotos"):
    conn.execute("ALTER TABLE dim_pilotos ADD COLUMN foto_url TEXT")

if "dias_trabalhados" not in cols("fato_piloto_autonomo_prova"):
    conn.execute("ALTER TABLE fato_piloto_autonomo_prova ADD COLUMN dias_trabalhados INTEGER")

if "link_avaliacao_externa" not in cols("fato_piloto_autonomo_prova"):
    conn.execute("ALTER TABLE fato_piloto_autonomo_prova ADD COLUMN link_avaliacao_externa TEXT")

# Tabela de cargos
conn.execute("""
CREATE TABLE IF NOT EXISTS dim_cargos_autonomos (
    id_cargo_autonomo INTEGER PRIMARY KEY AUTOINCREMENT,
    nome_cargo TEXT NOT NULL,
    descricao TEXT,
    status TEXT DEFAULT 'Ativo'
)
""")

if "id_cargo_autonomo" not in cols("dim_autonomos"):
    conn.execute("ALTER TABLE dim_autonomos ADD COLUMN id_cargo_autonomo INTEGER")

# Helpers
def get_or_create(table, unique_col, unique_value, payload):
    row = conn.execute(
        f"SELECT * FROM {table} WHERE LOWER({unique_col}) = LOWER(?) LIMIT 1",
        (unique_value,)
    ).fetchone()

    if row:
        return row[0]

    keys = list(payload.keys())
    sql = f"INSERT INTO {table} ({', '.join(keys)}) VALUES ({', '.join(['?'] * len(keys))})"
    cur = conn.execute(sql, [payload[k] for k in keys])
    return cur.lastrowid

# Cargos
id_mecanico = get_or_create("dim_cargos_autonomos", "nome_cargo", "Mecânico", {
    "nome_cargo": "Mecânico",
    "descricao": "Responsável pela parte mecânica do carro",
    "status": "Ativo",
})

id_engenheiro = get_or_create("dim_cargos_autonomos", "nome_cargo", "Engenheiro", {
    "nome_cargo": "Engenheiro",
    "descricao": "Responsável pela engenharia, setup e dados",
    "status": "Ativo",
})

id_preparador = get_or_create("dim_cargos_autonomos", "nome_cargo", "Preparador", {
    "nome_cargo": "Preparador",
    "descricao": "Responsável pela preparação e apoio operacional",
    "status": "Ativo",
})

# Tipos de categoria
id_carrera = get_or_create("dim_tipos_prova", "nome_tipo_prova", "Carrera Cup", {
    "nome_tipo_prova": "Carrera Cup",
    "descricao": "Tipo de categoria Porsche Cup",
    "status_tipo_prova": "Ativo",
})

id_sprint = get_or_create("dim_tipos_prova", "nome_tipo_prova", "Sprint Challenge", {
    "nome_tipo_prova": "Sprint Challenge",
    "descricao": "Tipo de categoria Porsche Cup",
    "status_tipo_prova": "Ativo",
})

# Etapas
id_interlagos = get_or_create("dim_etapas", "nome_etapa", "Etapa 01 - Interlagos", {
    "temporada": "2026",
    "nome_etapa": "Etapa 01 - Interlagos",
    "local": "São Paulo/SP",
    "data_inicio": "2026-03-13",
    "data_fim": "2026-03-15",
    "status_etapa": "Confirmada",
    "observacoes": "Dados de exemplo",
})

id_velocitta = get_or_create("dim_etapas", "nome_etapa", "Etapa 02 - Velocitta", {
    "temporada": "2026",
    "nome_etapa": "Etapa 02 - Velocitta",
    "local": "Mogi Guaçu/SP",
    "data_inicio": "2026-04-17",
    "data_fim": "2026-04-19",
    "status_etapa": "Planejada",
    "observacoes": "Dados de exemplo",
})

# Categorias
id_cat_carrera_interlagos = get_or_create("dim_provas", "nome_prova", "Carrera Cup - Interlagos", {
    "id_etapa": id_interlagos,
    "id_tipo_prova": id_carrera,
    "nome_prova": "Carrera Cup - Interlagos",
    "data_prova": "2026-03-14",
    "status_prova": "Confirmada",
    "observacoes": "Categoria de exemplo",
})

id_cat_sprint_interlagos = get_or_create("dim_provas", "nome_prova", "Sprint Challenge - Interlagos", {
    "id_etapa": id_interlagos,
    "id_tipo_prova": id_sprint,
    "nome_prova": "Sprint Challenge - Interlagos",
    "data_prova": "2026-03-15",
    "status_prova": "Confirmada",
    "observacoes": "Categoria de exemplo",
})

id_cat_carrera_velocitta = get_or_create("dim_provas", "nome_prova", "Carrera Cup - Velocitta", {
    "id_etapa": id_velocitta,
    "id_tipo_prova": id_carrera,
    "nome_prova": "Carrera Cup - Velocitta",
    "data_prova": "2026-04-18",
    "status_prova": "Planejada",
    "observacoes": "Categoria de exemplo",
})

# Pilotos
id_rafael = get_or_create("dim_pilotos", "nome_piloto", "Rafael Martins", {
    "nome_piloto": "Rafael Martins",
    "cpf": "111.111.111-11",
    "telefone": "(11) 99999-1001",
    "email": "rafael@exemplo.com",
    "equipe": "",
    "categoria_atual": "",
    "data_inclusao": "2026-01-10",
    "status_piloto": "Ativo",
    "observacoes": "Piloto de exemplo",
    "foto_url": "",
})

id_bruno = get_or_create("dim_pilotos", "nome_piloto", "Bruno Costa", {
    "nome_piloto": "Bruno Costa",
    "cpf": "222.222.222-22",
    "telefone": "(11) 99999-1002",
    "email": "bruno@exemplo.com",
    "equipe": "",
    "categoria_atual": "",
    "data_inclusao": "2026-01-12",
    "status_piloto": "Ativo",
    "observacoes": "Piloto de exemplo",
    "foto_url": "",
})

id_lucas = get_or_create("dim_pilotos", "nome_piloto", "Lucas Almeida", {
    "nome_piloto": "Lucas Almeida",
    "cpf": "333.333.333-33",
    "telefone": "(11) 99999-1003",
    "email": "lucas@exemplo.com",
    "equipe": "",
    "categoria_atual": "",
    "data_inclusao": "2026-01-15",
    "status_piloto": "Ativo",
    "observacoes": "Piloto de exemplo",
    "foto_url": "",
})

# Autônomos
def criar_autonomo(nome, cpf, cargo_id, cargo_nome, especialidade):
    row = conn.execute(
        "SELECT id_autonomo FROM dim_autonomos WHERE LOWER(nome_autonomo)=LOWER(?) LIMIT 1",
        (nome,)
    ).fetchone()

    if row:
        conn.execute(
            "UPDATE dim_autonomos SET id_cargo_autonomo=?, tipo_autonomo=?, status_autonomo='Ativo' WHERE id_autonomo=?",
            (cargo_id, cargo_nome, row["id_autonomo"])
        )
        return row["id_autonomo"]

    cur = conn.execute("""
        INSERT INTO dim_autonomos
        (nome_autonomo, cpf, telefone, email, tipo_autonomo, id_cargo_autonomo, especialidade, data_inclusao, status_autonomo, observacoes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        nome,
        cpf,
        "(11) 98888-0000",
        nome.lower().replace(" ", ".") + "@exemplo.com",
        cargo_nome,
        cargo_id,
        especialidade,
        "2026-01-20",
        "Ativo",
        "Autônomo de exemplo"
    ))

    return cur.lastrowid

id_joao = criar_autonomo("João Silva", "555.555.555-55", id_mecanico, "Mecânico", "Suspensão e freios")
id_pedro = criar_autonomo("Pedro Souza", "666.666.666-66", id_mecanico, "Mecânico", "Motor e transmissão")
id_carlos = criar_autonomo("Carlos Lima", "777.777.777-77", id_engenheiro, "Engenheiro", "Dados e setup")
id_mariana = criar_autonomo("Mariana Torres", "888.888.888-88", id_engenheiro, "Engenheiro", "Estratégia e telemetria")
id_andre = criar_autonomo("André Rocha", "999.999.999-99", id_preparador, "Preparador", "Preparação geral")
id_renato = criar_autonomo("Renato Alves", "444.444.444-44", id_preparador, "Preparador", "Apoio de box")

# Motivos
id_solicitacao = get_or_create("dim_motivos_troca", "motivo_troca", "Solicitação do piloto", {
    "motivo_troca": "Solicitação do piloto",
    "descricao": "Troca solicitada pelo piloto",
    "status": "Ativo",
})

id_indisponibilidade = get_or_create("dim_motivos_troca", "motivo_troca", "Indisponibilidade do autônomo", {
    "motivo_troca": "Indisponibilidade do autônomo",
    "descricao": "Autônomo indisponível para a categoria/etapa",
    "status": "Ativo",
})

# Criar alocações exemplo
def existe_alocacao(id_piloto, id_prova, funcao, status="Ativo"):
    return conn.execute("""
        SELECT id_fato
        FROM fato_piloto_autonomo_prova
        WHERE id_piloto=?
          AND id_prova=?
          AND funcao_autonomo=?
          AND status_vinculo=?
        LIMIT 1
    """, (id_piloto, id_prova, funcao, status)).fetchone()

def inserir_alocacao(id_piloto, id_autonomo, id_etapa, id_prova, funcao, valor, dias, status="Ativo", obs=""):
    if existe_alocacao(id_piloto, id_prova, funcao, status):
        return None

    cur = conn.execute("""
        INSERT INTO fato_piloto_autonomo_prova
        (id_piloto, id_autonomo, id_etapa, id_prova, funcao_autonomo,
         data_inicio_vinculo, status_vinculo, foi_substituido,
         valor_fechado_etapa, dias_trabalhados, status_pagamento, observacoes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        id_piloto, id_autonomo, id_etapa, id_prova, funcao,
        "2026-03-13", status, "Não",
        valor, dias, None, obs
    ))

    return cur.lastrowid

# Rafael - equipe completa em Interlagos
inserir_alocacao(id_rafael, id_joao, id_interlagos, id_cat_carrera_interlagos, "Mecânico", 3300, 3, "Ativo", "Equipe formada para Interlagos")
inserir_alocacao(id_rafael, id_carlos, id_interlagos, id_cat_carrera_interlagos, "Engenheiro", 5200, 3, "Ativo", "Engenharia de dados")
inserir_alocacao(id_rafael, id_andre, id_interlagos, id_cat_carrera_interlagos, "Preparador", 2400, 3, "Ativo", "Apoio de box")

# Bruno - equipe com substituição de mecânico
id_antigo = inserir_alocacao(id_bruno, id_pedro, id_interlagos, id_cat_sprint_interlagos, "Mecânico", 3000, 3, "Substituido", "Mecânico substituído durante a etapa")

if id_antigo:
    conn.execute("""
        UPDATE fato_piloto_autonomo_prova
        SET foi_substituido='Sim',
            id_autonomo_substituto=?,
            data_troca='2026-03-14',
            data_fim_vinculo='2026-03-14',
            id_motivo_troca=?,
            justificativa_troca='Piloto solicitou alteração para ajuste de trabalho no box.'
        WHERE id_fato=?
    """, (id_joao, id_solicitacao, id_antigo))

inserir_alocacao(id_bruno, id_joao, id_interlagos, id_cat_sprint_interlagos, "Mecânico", 3100, 2, "Ativo", "Entrou como substituto")
inserir_alocacao(id_bruno, id_mariana, id_interlagos, id_cat_sprint_interlagos, "Engenheiro", 5000, 3, "Ativo", "Engenharia Sprint")
inserir_alocacao(id_bruno, id_renato, id_interlagos, id_cat_sprint_interlagos, "Preparador", 2200, 3, "Ativo", "Preparador Sprint")

# Lucas - Velocitta
inserir_alocacao(id_lucas, id_pedro, id_velocitta, id_cat_carrera_velocitta, "Mecânico", 3500, 3, "Ativo", "Equipe prevista Velocitta")
inserir_alocacao(id_lucas, id_carlos, id_velocitta, id_cat_carrera_velocitta, "Engenheiro", 5400, 3, "Ativo", "Engenharia prevista")

conn.commit()
conn.close()

print("OK - Dados de exemplo populados.")

# ============================================================
# 2. Criar/atualizar router de Equipes Alocadas
# ============================================================

equipes_router = r'''from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import DimEtapa, DimProva, FatoPilotoAutonomoProva
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

    fatos = (
        query
        .order_by(
            FatoPilotoAutonomoProva.id_etapa,
            FatoPilotoAutonomoProva.id_prova,
            FatoPilotoAutonomoProva.id_piloto,
            FatoPilotoAutonomoProva.funcao_autonomo,
        )
        .all()
    )

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

    equipes = list(grupos.values())

    etapas = db.query(DimEtapa).order_by(DimEtapa.temporada.desc(), DimEtapa.nome_etapa).all()
    categorias = db.query(DimProva).order_by(DimProva.data_prova.desc()).all()

    return templates.TemplateResponse(
        "equipes/index.html",
        {
            "request": request,
            "equipes": equipes,
            "etapas": etapas,
            "categorias": categorias,
            "filtros": {
                "id_etapa": id_etapa,
                "id_prova": id_prova,
            },
            **flash_from_request(request),
        },
    )
'''

write(BASE / "app" / "routers" / "equipes.py", equipes_router)

# ============================================================
# 3. Criar tela visual de equipes alocadas
# ============================================================

equipes_template = r'''{% extends "base.html" %}

{% block header %}Equipes Alocadas{% endblock %}
{% block subtitle %}Visualize por etapa e categoria a equipe formada para cada piloto{% endblock %}

{% block header_action %}
<a class="quick-action primary" href="/operacao/nova-guiada">Nova Alocação</a>
<a class="quick-action light" href="/alocacoes">Gestão de Alocação</a>
{% endblock %}

{% block content %}

<section class="panel mb-6">
  <div class="panel-head">
    <div>
      <h3>Filtros</h3>
      <p class="text-sm text-zinc-500">Selecione uma etapa e, se necessário, uma categoria específica.</p>
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

<section class="ux-grid ux-grid-4 mb-6">
  <div class="ux-card">
    <div class="ux-muted">Equipes encontradas</div>
    <div class="ux-kpi">{{ equipes|length }}</div>
  </div>

  <div class="ux-card">
    <div class="ux-muted">Pilotos com equipe</div>
    <div class="ux-kpi">{{ equipes|length }}</div>
  </div>

  <div class="ux-card">
    <div class="ux-muted">Com substituição</div>
    <div class="ux-kpi">{{ equipes|selectattr("substituidos")|list|length }}</div>
  </div>

  <div class="ux-card">
    <div class="ux-muted">Visual por categoria</div>
    <div class="ux-kpi">OK</div>
  </div>
</section>

<div class="ux-grid ux-grid-3">
  {% for equipe in equipes %}
    <section class="ux-card">
      <div class="flex items-start justify-between gap-3 mb-5">
        <div class="flex items-center gap-4">
          {% if equipe.piloto.foto_url %}
            <img src="{{ equipe.piloto.foto_url }}" style="width:64px;height:64px;border-radius:999px;object-fit:cover;">
          {% else %}
            <div style="width:64px;height:64px;border-radius:999px;background:#18181b;color:white;display:flex;align-items:center;justify-content:center;font-weight:900;font-size:22px;">
              {{ equipe.piloto.nome_piloto[:1] }}
            </div>
          {% endif %}

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
            <div class="flex items-center justify-between gap-2">
              <div>
                <div class="font-black text-zinc-950">{{ f.funcao_autonomo }}</div>
                <div class="font-bold">{{ f.autonomo.nome_autonomo }}</div>
                <div class="ux-muted">{{ f.autonomo.especialidade or f.autonomo.tipo_autonomo or '-' }}</div>
              </div>
              <span class="ux-pill green">Ativo</span>
            </div>

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

      <div class="mt-5 pt-4 border-t border-zinc-200">
        {% set media_dia = (equipe.valor_total / equipe.dias_total) if equipe.valor_total and equipe.dias_total else None %}

        <div class="grid grid-cols-3 gap-2 text-sm">
          <div>
            <div class="ux-muted">Total pacote</div>
            <div class="font-black">{{ equipe.valor_total|money_br }}</div>
          </div>

          <div>
            <div class="ux-muted">Dias totais</div>
            <div class="font-black">{{ equipe.dias_total or '-' }}</div>
          </div>

          <div>
            <div class="ux-muted">Média/dia</div>
            <div class="font-black">
              {% if media_dia %}
                {{ media_dia|money_br }}
              {% else %}
                -
              {% endif %}
            </div>
          </div>
        </div>
      </div>
    </section>
  {% else %}
    <section class="ux-card">
      <h3 class="ux-card-title">Nenhuma equipe encontrada</h3>
      <p class="ux-muted">Use a alocação guiada para formar a equipe por piloto, etapa e categoria.</p>
      <div class="ux-actions-row mt-5">
        <a class="btn-primary" href="/operacao/nova-guiada">Criar Alocação</a>
      </div>
    </section>
  {% endfor %}
</div>

<script>
(function() {
  const etapa = document.getElementById("id_etapa_filtro");
  const categoria = document.getElementById("id_categoria_filtro");

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

write(BASE / "app" / "templates" / "equipes" / "index.html", equipes_template)

# ============================================================
# 4. Registrar rota /equipes no main.py
# ============================================================

main_path = BASE / "app" / "main.py"
backup(main_path)

main = main_path.read_text(encoding="utf-8")

if "app.routers.equipes" not in main:
    bloco = r'''

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
    main = main.rstrip() + bloco + "\n"

main_path.write_text(main, encoding="utf-8")

# ============================================================
# 5. Garantir menu lateral
# ============================================================

base_path = BASE / "app" / "templates" / "base.html"
backup(base_path)

base = base_path.read_text(encoding="utf-8")

# Remove duplicados antigos
base = base.replace("('/equipes','Equipes por Piloto'),", "")
base = base.replace("('/equipes','👥 Equipes por Piloto'),", "")
base = base.replace("('/equipes','Equipes Alocadas'),", "")
base = base.replace("('/equipes','👥 Equipes Alocadas'),", "")

# Insere em Operação antes de Gestão de Alocação
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
    elif "('/alocacoes','Gestao de Alocacao')," in base:
        base = base.replace(
            "('/alocacoes','Gestao de Alocacao'),",
            "('/equipes','👥 Equipes Alocadas'),('/alocacoes','Gestao de Alocacao'),"
        )
    else:
        base = base.replace(
            "('Operação', [",
            "('Operação', [('/equipes','👥 Equipes Alocadas'),"
        )
        base = base.replace(
            "('Operacao', [",
            "('Operacao', [('/equipes','👥 Equipes Alocadas'),"
        )

base_path.write_text(base, encoding="utf-8")

# ============================================================
# 6. Garantir CSS para cards
# ============================================================

css_path = BASE / "app" / "static" / "css" / "style.css"

css = css_path.read_text(encoding="utf-8") if css_path.exists() else ""

css_add = r'''

/* Equipes Alocadas */
.ux-grid {
  display: grid;
  gap: 1rem;
}

.ux-grid-3 {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.ux-grid-4 {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

@media (max-width: 1100px) {
  .ux-grid-3,
  .ux-grid-4 {
    grid-template-columns: 1fr;
  }
}

.ux-card {
  background: #fff;
  border: 1px solid #e4e4e7;
  border-radius: 1.25rem;
  padding: 1.15rem;
  box-shadow: 0 18px 40px rgba(15, 23, 42, .06);
}

.ux-card-title {
  font-size: 1rem;
  font-weight: 900;
  color: #18181b;
  margin-bottom: .15rem;
}

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

.ux-pill.green {
  background: #dcfce7;
  color: #166534;
}

.ux-pill.yellow {
  background: #fef9c3;
  color: #854d0e;
}

.ux-help {
  background: #fff7ed;
  border: 1px solid #fed7aa;
  color: #9a3412;
  padding: .85rem 1rem;
  border-radius: 1rem;
  font-size: .9rem;
}

.ux-actions-row {
  display: flex;
  gap: .45rem;
  flex-wrap: wrap;
  align-items: center;
}
'''

if "Equipes Alocadas" not in css:
    css_path.parent.mkdir(parents=True, exist_ok=True)
    css_path.write_text(css + css_add, encoding="utf-8")

# ============================================================
# 7. Testar app
# ============================================================

import sys
vendor = BASE / ".vendor"
if vendor.exists():
    sys.path.insert(0, str(vendor))

from app.main import app

rotas = sorted([getattr(r, "path", "") for r in app.routes])

print("")
print("ROTAS:")
for r in ["/equipes", "/alocacoes", "/operacao/nova-guiada"]:
    print(f" - {r}: {'OK' if r in rotas else 'NÃO ENCONTRADA'}")

print("")
print("PATCH CONCLUÍDO.")
print("Menu novo:")
print(" - Operação > Equipes Alocadas")
print("")
print("Teste direto:")
print("http://127.0.0.1:8000/equipes")
print("")
print("Dados de exemplo criados para:")
print(" - Etapa 01 - Interlagos")
print(" - Etapa 02 - Velocitta")
print(" - Rafael Martins")
print(" - Bruno Costa")
print(" - Lucas Almeida")
