"""Módulo Indicadores — dashboards analíticos com dados do Feedz via OData."""

from __future__ import annotations

import calendar
import os
import re
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

import requests
from catworld import CatworldClient
from fastapi import APIRouter, Request
from sqlalchemy import select, text

from app.template_config import templates
from app.utils import competencia_de, data_para_date, empresa_curta

router = APIRouter(tags=["indicadores"])

# ─── OData ────────────────────────────────────────────────────────────────────

def _fetch_feedz(entity: str) -> list[dict]:
    base_url = os.getenv("FEEDZ_ODATA_URL", "https://catworld.77indicadores.com.br/api/odata/porsche/feedz")
    token = os.getenv("FEEDZ_TOKEN") or os.getenv("CATWORLD_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    url = f"{base_url}/{entity}"
    rows: list[dict] = []
    while url:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        rows.extend(data.get("value", []))
        url = data.get("@odata.nextLink") or data.get("odata.nextLink")
    return rows


# ─── helpers de data ──────────────────────────────────────────────────────────

def _parse_date(val) -> Optional[date]:
    if val is None:
        return None
    s = str(val).strip().split("T")[0].split(" ")[0]
    if not s or s.lower() in ("none", "null", "sem data"):
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


def _eomonth(d: date) -> date:
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def _somonth(d: date) -> date:
    return date(d.year, d.month, 1)


def _mes_label(d: date) -> str:
    meses = ["jan","fev","mar","abr","mai","jun","jul","ago","set","out","nov","dez"]
    return f"{meses[d.month - 1]}.{str(d.year)[2:]}"


def _mes_label_upper(d: date) -> str:
    return _mes_label(d).upper()


# ─── processamento ────────────────────────────────────────────────────────────

def _normalizar_colabs(rows: list[dict]) -> list[dict]:
    result = []
    for r in rows:
        nome = str(r.get("nome") or "").strip().upper()
        if not nome:
            continue
        data_adm = (
            _parse_date(r.get("data_adm"))
            or _parse_date(r.get("data_admissao"))
            or _parse_date(r.get("data_de_cadastro"))
            or _parse_date(r.get("criado_em"))
        )
        data_demissa = (
            _parse_date(r.get("data_demissa"))
            or _parse_date(r.get("ultimo_dia_trabalhado"))
        )
        # Feedz envia "desligamento_motivo" e "desligamento_tipo" (não o inverso)
        motivo_raw = str(r.get("desligamento_motivo") or r.get("motivo_desligamento") or r.get("motivo_demissao") or "").strip()
        tipo_desl_raw = str(r.get("desligamento_tipo") or r.get("tipo_desligamento") or "").strip()
        tipo_lower  = tipo_desl_raw.lower()
        motivo_lower = motivo_raw.lower()
        # Motivo involuntário tem prioridade: o Feedz registra tipo="Pedido de Demissão"
        # mesmo para demissões involuntárias, usando o motivo para indicar a causa real
        _INV_MOTIVO = ("baixo desempenho", "alinhamento", "reestrutura", "encerramento", "involunt", "justa causa")
        _INV_TIPO   = ("com justa causa", "sem justa causa", "comum acordo",
                       "término de contrato", "termino de contrato")
        _VOL_MOTIVO = ("pessoal", "oportunidade", "salário", "salario", "voluntar", "nova oportunidade")
        _VOL_TIPO   = ("pedido de demissão", "pedido de demissao", "aposentadoria", "voluntár", "voluntar")
        if any(k in motivo_lower for k in _INV_MOTIVO) or any(k in tipo_lower for k in _INV_TIPO):
            tipo_desl = "Involuntário"
        elif any(k in motivo_lower for k in _VOL_MOTIVO) or any(k in tipo_lower for k in _VOL_TIPO):
            tipo_desl = "Voluntário"
        else:
            tipo_desl = "Não informado"

        result.append({
            "nome": nome,
            "data_adm": data_adm,
            "data_demissa": data_demissa,
            "situacao": str(r.get("situacao") or "").strip() or "Não informado",
            "tipo_de_vinculo": str(r.get("tipo_de_vinculo") or "").strip() or "Não informado",
            "sexo": str(r.get("sexo") or "").strip() or "Não informado",
            "unidade": str(r.get("unidade") or "").strip() or "Não informado",
            "grau_de_instrucao": str(r.get("grau_de_instrucao") or "").strip() or "Não informado",
            "departamento": str(r.get("departamento") or r.get("setor") or r.get("area") or "").strip().upper() or "Não informado",
            "empresa": str(r.get("empresa") or r.get("razao_social") or r.get("cnpj_empresa") or "").strip().upper() or "Não informado",
            "motivo_desligamento": motivo_raw or "Não informado",
            "tipo_desligamento": tipo_desl,
        })
    return result


def _is_ativo(c: dict, ref: date) -> bool:
    sit = (c.get("situacao") or "").strip()
    adm, dem = c["data_adm"], c["data_demissa"]
    # Status vazio / não informado NÃO entra no quadro ativo (registro incompleto do Feedz)
    if not sit or sit == "Não informado":
        return False
    # Feedz marca situacao="Ativo" para quem está no quadro; confia nisso como fonte primária
    if sit == "Ativo" and (dem is None or dem > ref):
        return True
    # Fallback por datas para funcionários que já saíram (situacao != "Ativo")
    if adm is None or adm > ref:
        return False
    return dem is None or dem > ref


def _contar_por_campo(colabs: list[dict], campo: str, ref: date) -> list[tuple[str, int]]:
    counts: dict[str, int] = defaultdict(int)
    for c in colabs:
        if _is_ativo(c, ref):
            counts[c[campo]] += 1
    return sorted(counts.items(), key=lambda x: -x[1])


def _evolucao_6m(colabs: list[dict], ref: date) -> list[tuple[date, str, int]]:
    # Sempre termina no mês atual independente do período selecionado
    hoje = date.today()
    base = _eomonth(hoje)
    result = []
    for i in range(5, -1, -1):
        ano, mes = base.year, base.month - i
        while mes <= 0:
            mes += 12; ano -= 1
        fim = _eomonth(date(ano, mes, 1))
        # Não projeta além do período de referência selecionado
        fim_calc = min(fim, ref)
        total = sum(1 for c in colabs if _is_ativo(c, fim_calc))
        result.append((fim_calc, _mes_label_upper(fim_calc), total))
    return result


# ─── geração SVG do gráfico ───────────────────────────────────────────────────

_XS = [45, 205, 365, 525, 685, 845]  # posições x fixas para 6 pontos

def _chart_svg(evolucao: list[tuple[date, str, int]]) -> str:
    vals = [v for _, _, v in evolucao]
    labels = [l for _, l, _ in evolucao]
    n = len(vals)
    if n == 0:
        return ""

    top, bot = 45, 165
    height = bot - top
    vmax, vmin = max(vals), min(vals)
    spread = vmax - vmin or 1

    xs = _XS[:n]

    def y(v: int) -> float:
        # distribui com 10% de padding no topo
        return bot - (v - vmin) / spread * height * 0.88 - height * 0.06

    ys = [y(v) for v in vals]
    pts_line = " ".join(f"{xs[i]},{ys[i]:.1f}" for i in range(n))
    pts_area = f"{xs[0]},{bot} " + pts_line + f" {xs[-1]},{bot}"

    circles = ""
    for i in range(n):
        circles += (
            f"<circle class='point' cx='{xs[i]}' cy='{ys[i]:.1f}' r='4.5'/>"
            f"<text class='value' x='{xs[i]}' y='{ys[i]-10:.1f}' text-anchor='middle'>{vals[i]}</text>"
            f"<text class='label' x='{xs[i]}' y='198' text-anchor='middle'>{labels[i]}</text>"
        )

    return f"""<svg class="chart-svg" viewBox="0 0 900 210" preserveAspectRatio="none">
  <defs>
    <linearGradient id="areaGradient" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#e10600" stop-opacity=".22"/>
      <stop offset="100%" stop-color="#e10600" stop-opacity=".02"/>
    </linearGradient>
  </defs>
  <line class="gridline" x1="45" y1="45" x2="870" y2="45"/>
  <line class="gridline" x1="45" y1="95" x2="870" y2="95"/>
  <line class="gridline" x1="45" y1="145" x2="870" y2="145"/>
  <path class="area" d="M{pts_area} Z"/>
  <path class="line" d="M{pts_line}"/>
  {circles}
</svg>"""


# ─── CSS completo ─────────────────────────────────────────────────────────────

_CSS = """<style>
:root{
  --bg:#f3f4f6;--surface:#ffffff;--ink:#161616;--muted:#6f7378;--line:#e7e7e7;
  --red:#e10600;--red-2:#ff3b30;--red-soft:#fff0ef;--black:#121212;
  --green:#1f9d62;--amber:#f5a623;--blue:#2f80ed;
  --shadow:0 12px 34px rgba(0,0,0,.08);--shadow-soft:0 5px 18px rgba(0,0,0,.05);
  --radius:22px;
}
*{box-sizing:border-box}
.dashboard{
  width:100%;font-family:Inter,'Segoe UI',Arial,sans-serif;
  color:var(--ink);padding:0;
}
.topbar{
  display:grid;grid-template-columns:1fr auto;
  gap:20px;align-items:center;margin-bottom:16px;
}
.brand{display:flex;align-items:center;gap:14px}
.brand-mark{
  width:48px;height:48px;border-radius:16px;
  background:linear-gradient(145deg,#1c1c1c,#050505);
  display:grid;place-items:center;box-shadow:0 10px 25px rgba(0,0,0,.16);
  flex-shrink:0;
}
.brand-mark svg{width:24px;height:24px}
.eyebrow{font-size:11px;font-weight:800;letter-spacing:.18em;text-transform:uppercase;color:var(--red);margin-bottom:3px}
.brand h1{font-size:22px;line-height:1;margin:0;letter-spacing:-.03em}
.brand .subtitle{margin-top:4px;font-size:12px;color:var(--muted)}
.filters{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.filter{background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:8px 14px;min-width:150px}
.filter label{display:block;font-size:10px;font-weight:700;color:#9ca3af;text-transform:uppercase;letter-spacing:.08em;margin-bottom:3px}
.filter select{width:100%;border:0;background:transparent;outline:none;color:#111827;font-size:13px;font-weight:600;cursor:pointer}
.hero{
  background:linear-gradient(135deg,#171717 0%,#0c0c0c 58%,#250000 100%);
  color:#fff;border-radius:26px;padding:22px 24px;
  display:grid;grid-template-columns:1.3fr .7fr;gap:18px;
  box-shadow:0 20px 46px rgba(0,0,0,.15);position:relative;overflow:hidden;margin-bottom:14px;
}
.hero:after{content:"";position:absolute;width:270px;height:270px;right:-85px;top:-110px;border:52px solid rgba(225,6,0,.18);border-radius:50%}
.hero:before{content:"";position:absolute;width:150px;height:150px;right:220px;bottom:-110px;background:rgba(225,6,0,.14);border-radius:50%;filter:blur(2px)}
.hero-left,.hero-kpis{position:relative;z-index:2}
.hero-left{display:flex;flex-direction:column;justify-content:space-between;min-height:140px}
.hero-title{display:flex;align-items:flex-start;justify-content:space-between;gap:16px}
.hero-title h2{font-size:20px;margin:0 0 4px;letter-spacing:-.03em}
.hero-title p{margin:0;color:#b9b9b9;font-size:11px}
.period-badge{background:rgba(255,255,255,.09);border:1px solid rgba(255,255,255,.13);border-radius:999px;padding:7px 11px;font-size:11px;font-weight:800;white-space:nowrap;height:fit-content}
.hero-summary{display:flex;align-items:flex-end;gap:14px;margin-top:12px}
.big-number{font-size:54px;font-weight:900;letter-spacing:-.06em;line-height:.9}
.big-caption{color:#b9b9b9;font-size:11px;max-width:220px;line-height:1.35;padding-bottom:2px}
.delta{display:inline-flex;align-items:center;gap:5px;background:rgba(31,157,98,.17);color:#8ef0bd;padding:5px 9px;border-radius:999px;font-size:10px;font-weight:800;margin-top:6px}
.hero-kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;align-items:stretch}
.mini-kpi{background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.1);border-radius:16px;padding:12px;display:flex;flex-direction:column;justify-content:space-between;min-height:100px}
.mini-kpi .icon{width:28px;height:28px;border-radius:9px;display:grid;place-items:center;background:rgba(255,255,255,.08);font-size:14px}
.mini-kpi strong{font-size:26px;line-height:1;letter-spacing:-.04em}
.mini-kpi span{font-size:9px;color:#bdbdbd;text-transform:uppercase;letter-spacing:.08em;font-weight:800}
.mini-kpi.red{background:linear-gradient(160deg,rgba(225,6,0,.25),rgba(255,255,255,.04))}
.mini-kpi.green{background:linear-gradient(160deg,rgba(31,157,98,.18),rgba(255,255,255,.04))}
.mini-kpi.amber{background:linear-gradient(160deg,rgba(245,166,35,.22),rgba(255,255,255,.04))}
.mini-kpi.blue{background:linear-gradient(160deg,rgba(47,128,237,.20),rgba(255,255,255,.04))}
.content-grid{display:grid;grid-template-columns:1.6fr .4fr;gap:14px;margin-bottom:14px}
.card{background:rgba(255,255,255,.92);border:1px solid rgba(0,0,0,.06);border-radius:var(--radius);box-shadow:var(--shadow-soft)}
.chart-card{padding:18px 18px 10px;min-height:260px}
.card-head{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;margin-bottom:8px}
.card-head h3{margin:0;font-size:15px;letter-spacing:-.02em}
.card-head p{margin:4px 0 0;color:var(--muted);font-size:11px}
.pill{display:inline-flex;align-items:center;gap:6px;border-radius:999px;padding:6px 10px;font-size:10px;font-weight:800;color:#3f4144;background:#f3f4f5;border:1px solid #e7e8ea;white-space:nowrap}
.chart-wrap{height:195px;position:relative}
.chart-svg{width:100%;height:100%;display:block}
.gridline{stroke:#ececee;stroke-width:1}
.area{fill:url(#areaGradient)}
.line{fill:none;stroke:var(--red);stroke-width:3.2;stroke-linecap:round;stroke-linejoin:round}
.point{fill:#fff;stroke:var(--red);stroke-width:3}
.label{font-size:10px;fill:#7b7e83;font-weight:700}
.value{font-size:11px;fill:#242424;font-weight:900}
.insight-card{padding:18px;display:flex;flex-direction:column;gap:14px;min-height:260px}
.donut-box{display:grid;place-items:center;flex:1;position:relative}
.donut{--p:0;width:120px;aspect-ratio:1;border-radius:50%;background:conic-gradient(var(--red) calc(var(--p)*1%),#efeff1 0);position:relative}
.donut:after{content:"";position:absolute;inset:17px;background:white;border-radius:50%;box-shadow:inset 0 0 0 1px #ededed}
.donut-text{position:absolute;z-index:2;text-align:center}
.donut-text strong{display:block;font-size:24px;letter-spacing:-.04em}
.donut-text span{font-size:10px;color:var(--muted);font-weight:800}
.insight-list{display:grid;gap:7px}
.insight{display:flex;justify-content:space-between;align-items:center;font-size:11px;padding:8px 10px;background:#f7f7f8;border-radius:11px}
.insight b{font-size:12px}
.breakdowns{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}
.break-card{padding:16px}
.break-title{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px}
.break-title h4{margin:0;font-size:14px;letter-spacing:-.02em}
.tiny-icon{width:28px;height:28px;border-radius:10px;display:grid;place-items:center;background:var(--red-soft);color:var(--red);font-size:14px}
.rows{display:grid;gap:10px}
.row{display:grid;grid-template-columns:minmax(80px,1fr) 1.2fr auto;align-items:center;gap:8px}
.row .name{font-size:11px;color:#54575b;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.track{height:6px;background:#ececee;border-radius:999px;overflow:hidden}
.bar{height:100%;border-radius:999px;background:linear-gradient(90deg,var(--red),var(--red-2));width:var(--w);min-width:2px}
.metric{font-size:10px;color:#83868a;white-space:nowrap;text-align:right}
.metric b{font-size:11px;color:#1d1d1d}
.footer-note{margin-top:10px;display:flex;justify-content:space-between;color:#8a8d91;font-size:10px;padding:0 4px}
@media(max-width:1100px){.topbar{grid-template-columns:1fr}.content-grid{grid-template-columns:1fr}.breakdowns{grid-template-columns:repeat(2,1fr)}.hero{grid-template-columns:1fr}}
@media(max-width:650px){.hero-kpis{grid-template-columns:repeat(2,1fr)}.breakdowns{grid-template-columns:1fr}.big-number{font-size:42px}}
</style>"""


# ─── geração HTML ─────────────────────────────────────────────────────────────

def _html_rows(itens: list[tuple[str, int]], total: int) -> str:
    parts = []
    for label, val in itens:
        pct = val / total * 100 if total else 0
        parts.append(
            f"<div class='row'>"
            f"<div class='name'>{label}</div>"
            f"<div class='track'><div class='bar' style='--w:{pct:.1f}%'></div></div>"
            f"<div class='metric'><b>{val:,}</b> · {pct:.1f}%</div>"
            f"</div>"
        )
    return "".join(parts)


def _build_headcount_html(
    colabs: list[dict],
    ref: date,
    meses_opcoes: list[tuple[str, str]],
    mes_sel: str,
    todas_empresas: list[str] | None = None,
    todos_deptos: list[str] | None = None,
    empresa_sel: str = "",
    depto_sel: str = "",
) -> str:
    total_ativos = sum(1 for c in colabs if _is_ativo(c, ref))

    # situação breakdown para mini-kpis
    sit_map = defaultdict(int)
    for c in colabs:
        if _is_ativo(c, ref):
            sit_map[c["situacao"]] += 1

    qtd_ativos   = sit_map.get("Ativo", sit_map.get("ativo", 0))
    qtd_afastado = sum(v for k, v in sit_map.items() if "afas" in k.lower() or "licen" in k.lower())

    # admitidos e demitidos no mês
    ini = _somonth(ref)
    qtd_admitidos = sum(1 for c in colabs if c["data_adm"] and ini <= c["data_adm"] <= ref)
    qtd_demitidos = sum(1 for c in colabs if c["data_demissa"] and ini <= c["data_demissa"] <= ref)

    # delta 6 meses
    evolucao = _evolucao_6m(colabs, ref)
    val_inicio = evolucao[0][2] if evolucao else total_ativos
    delta = (total_ativos - val_inicio) / val_inicio * 100 if val_inicio else 0
    delta_txt = f"{'↗' if delta >= 0 else '↘'} {abs(delta):.1f}% em 6 meses"
    delta_style = "background:rgba(31,157,98,.17);color:#8ef0bd" if delta >= 0 else "background:rgba(225,6,0,.2);color:#fca5a5"

    pico = max(v for _, _, v in evolucao) if evolucao else total_ativos

    # donut — % de ativos sobre total
    pct_ativo = qtd_ativos / total_ativos * 100 if total_ativos else 0
    donut_p = f"{pct_ativo:.1f}"

    periodo_label = _mes_label(ref)

    # seletor de período
    opts = "".join(
        f"<option value='{v}'{' selected' if v == mes_sel else ''}>{l}</option>"
        for v, l in meses_opcoes
    )

    # opções de empresa e departamento
    emp_opts = "<option value=''>Todas</option>" + "".join(
        f"<option value='{e}'{' selected' if e == (empresa_sel or '').upper() else ''}>{empresa_curta(e)}</option>"
        for e in (todas_empresas or [])
    )
    dep_opts = "<option value=''>Todos</option>" + "".join(
        f"<option value='{d}'{' selected' if d == (depto_sel or '').upper() else ''}>{d.title()}</option>"
        for d in (todos_deptos or [])
    )

    # breakdowns
    vinculos  = _contar_por_campo(colabs, "tipo_de_vinculo", ref)
    sexo      = _contar_por_campo(colabs, "sexo", ref)
    unidade   = _contar_por_campo(colabs, "unidade", ref)
    instrucao = _contar_por_campo(colabs, "grau_de_instrucao", ref)

    return f"""<div class="dashboard">{_CSS}

<header class="topbar">
  <div class="brand">
    <div class="brand-mark">
      <svg viewBox="0 0 24 24" fill="none">
        <path d="M5 18V8.5M12 18V4M19 18v-6.5" stroke="#fff" stroke-width="2.2" stroke-linecap="round"/>
        <circle cx="5" cy="6" r="2" fill="#e10600"/>
        <circle cx="12" cy="2.5" r="2" fill="#e10600"/>
        <circle cx="19" cy="9" r="2" fill="#e10600"/>
      </svg>
    </div>
    <div>
      <div class="eyebrow">People Analytics</div>
      <h1>RH · Headcount Executivo</h1>
      <div class="subtitle">Porsche Carrera Cup Brasil &amp; Sprint Challenge Brasil</div>
    </div>
  </div>
  <div class="filters">
    <form method="get" style="margin:0;display:contents">
      <div class="filter">
        <label>Competência</label>
        <select name="mes" onchange="this.form.submit()"
          style="width:100%;border:0;background:transparent;outline:none;color:#252525;font-size:13px;font-weight:700;cursor:pointer">
          {opts}
        </select>
      </div>
      <div class="filter">
        <label>Empresa</label>
        <select name="empresa" onchange="this.form.submit()"
          style="width:100%;border:0;background:transparent;outline:none;color:#252525;font-size:13px;font-weight:700;cursor:pointer">
          {emp_opts}
        </select>
      </div>
      <div class="filter">
        <label>Departamento</label>
        <select name="departamento" onchange="this.form.submit()"
          style="width:100%;border:0;background:transparent;outline:none;color:#252525;font-size:13px;font-weight:700;cursor:pointer">
          {dep_opts}
        </select>
      </div>
    </form>
  </div>
</header>

<section class="hero">
  <div class="hero-left">
    <div class="hero-title">
      <div>
        <h2>Headcount Ativo</h2>
        <p>Posição consolidada no último dia do período selecionado</p>
      </div>
      <div class="period-badge">Posição · {periodo_label}</div>
    </div>
    <div class="hero-summary">
      <div class="big-number">{total_ativos:,}</div>
      <div class="big-caption">
        colaboradores no quadro ativo
        <div class="delta" style="{delta_style}">{delta_txt}</div>
      </div>
    </div>
  </div>

  <div class="hero-kpis">
    <div class="mini-kpi green">
      <div class="icon">✓</div>
      <strong>{qtd_ativos or total_ativos:,}</strong>
      <span>Ativos</span>
    </div>
    <div class="mini-kpi blue">
      <div class="icon">＋</div>
      <strong>{qtd_admitidos:,}</strong>
      <span>Admitidos</span>
    </div>
    <div class="mini-kpi red">
      <div class="icon">↘</div>
      <strong>{qtd_demitidos:,}</strong>
      <span>Desligados</span>
    </div>
    <div class="mini-kpi amber">
      <div class="icon">⏸</div>
      <strong>{qtd_afastado:,}</strong>
      <span>Afastados</span>
    </div>
  </div>
</section>

<section class="content-grid">
  <article class="card chart-card">
    <div class="card-head">
      <div>
        <h3>Evolução mensal do headcount</h3>
        <p>Colaboradores ativos por competência</p>
      </div>
      <div class="pill">● Últimos 6 meses</div>
    </div>
    <div class="chart-wrap">
      {_chart_svg(evolucao)}
    </div>
  </article>

  <aside class="card insight-card">
    <div class="card-head">
      <div>
        <h3>Taxa de ocupação</h3>
        <p>Ativos sobre o quadro total</p>
      </div>
    </div>
    <div class="donut-box">
      <div class="donut" style="--p:{donut_p}"></div>
      <div class="donut-text">
        <strong>{donut_p}%</strong>
        <span>quadro ativo</span>
      </div>
    </div>
    <div class="insight-list">
      <div class="insight"><span>Variação 6 meses</span><b>{delta_txt}</b></div>
      <div class="insight"><span>Pico no período</span><b>{pico:,}</b></div>
    </div>
  </aside>
</section>

<section class="breakdowns">
  <article class="card break-card">
    <div class="break-title"><h4>Tipo de vínculo</h4><div class="tiny-icon">⌘</div></div>
    <div class="rows">{_html_rows(vinculos, total_ativos)}</div>
  </article>
  <article class="card break-card">
    <div class="break-title"><h4>Sexo</h4><div class="tiny-icon">◐</div></div>
    <div class="rows">{_html_rows(sexo, total_ativos)}</div>
  </article>
  <article class="card break-card">
    <div class="break-title"><h4>Unidade</h4><div class="tiny-icon">⌂</div></div>
    <div class="rows">{_html_rows(unidade, total_ativos)}</div>
  </article>
  <article class="card break-card">
    <div class="break-title"><h4>Grau de instrução</h4><div class="tiny-icon">▣</div></div>
    <div class="rows">{_html_rows(instrucao, total_ativos)}</div>
  </article>
</section>

<div class="footer-note">
  <span>Base: vínculos ativos no último dia da competência selecionada.</span>
  <span>RH Analytics · Sistema Porsche</span>
</div>
</div>"""


# ─── turnover: cálculos ───────────────────────────────────────────────────────

def _turnover_mensal(colabs: list[dict], ano: int) -> list[dict]:
    """Retorna métricas mensais de turnover para o ano."""
    hoje = date.today()
    result = []
    for m in range(1, 13):
        fim = _eomonth(date(ano, m, 1))
        ini = _somonth(fim)
        adm  = [c for c in colabs if c["data_adm"]    and ini <= c["data_adm"]    <= fim]
        dem  = [c for c in colabs if c["data_demissa"] and ini <= c["data_demissa"] <= fim]
        hc   = sum(1 for c in colabs if _is_ativo(c, fim))
        hc_ini = sum(1 for c in colabs if _is_ativo(c, date(ini.year, ini.month, 1) - __import__("datetime").timedelta(days=1)))
        media = (hc + hc_ini) / 2 or 1
        turnover_pct = len(dem) / media * 100
        futuro = fim > hoje
        result.append({
            "mes": m, "label": _mes_label(date(ano, m, 1)),
            "admitidos": len(adm), "demitidos": len(dem),
            "headcount": hc, "turnover_pct": turnover_pct,
            "futuro": futuro,
            "dem_colabs": dem,
        })
    return result


def _turnover_svg(meses: list[dict]) -> str:
    """Gera SVG do gráfico de linha de turnover % para N meses (sem meses futuros)."""
    n = len(meses)
    if not n:
        return ""
    vals = [m["turnover_pct"] for m in meses]
    vmax = max(vals) if any(v > 0 for v in vals) else 5
    vmax = max(vmax * 1.1, 5)

    W, top, bot, pad = 620, 40, 180, 50
    xs = [pad + i * (W - 2 * pad) / max(n - 1, 1) for i in range(n)]

    def fy(v): return bot - (v / vmax) * (bot - top)

    pts = [(xs[i], fy(m["turnover_pct"])) for i, m in enumerate(meses)]
    line_d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    area_d = f"M{pts[0][0]:.1f},{bot} " + " ".join(f"L{x:.1f},{y:.1f}" for x, y in pts) + f" L{pts[-1][0]:.1f},{bot} Z"

    circles = "".join(f"<circle class='line-point' cx='{x:.1f}' cy='{y:.1f}' r='4'/>" for x, y in pts)
    labels  = "".join(
        f"<text class='label' x='{xs[i]:.1f}' y='215' text-anchor='middle' transform='rotate(-35 {xs[i]:.1f} 215)'>{m['label']}</text>"
        for i, m in enumerate(meses)
    )
    gridlines = "".join(
        f"<line class='gridline' x1='{pad}' y1='{fy(v):.1f}' x2='{W-pad}' y2='{fy(v):.1f}'/>"
        f"<text class='label' x='{pad-6}' y='{fy(v)+4:.1f}' text-anchor='end'>{v:.0f}%</text>"
        for v in [vmax * 0.75, vmax * 0.5, vmax * 0.25, 0]
    )
    return f"""<svg class="line-svg" viewBox="0 0 {W} 240" preserveAspectRatio="none">
  <defs><linearGradient id="turnArea" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0%" stop-color="#e10600" stop-opacity=".18"/>
    <stop offset="100%" stop-color="#e10600" stop-opacity=".02"/>
  </linearGradient></defs>
  {gridlines}
  <path fill="url(#turnArea)" d="{area_d}"/>
  <path class="line" d="{line_d}"/>
  {circles}
  {labels}
</svg>"""


def _bar_chart_html(meses: list[dict]) -> str:
    """Gera barras empilhadas admitidos/demitidos por mês."""
    if not meses:
        return "<p style='color:#9ca3af;font-size:12px;padding:12px'>Sem dados no período selecionado.</p>"
    max_val = max((m["admitidos"] + m["demitidos"]) for m in meses) or 1
    BAR_H = 200
    cols = []
    for m in meses:
        ha = int(m["admitidos"] / max_val * BAR_H)
        hd = int(m["demitidos"] / max_val * BAR_H)
        style = "placeholder" if m["futuro"] else ""
        op = " opacity:.45;" if m["futuro"] else ""
        seg_a = f"<div class='seg red' style='height:{ha}px;{op}'>{m['admitidos'] if m['admitidos'] else ''}</div>" if ha > 0 else ""
        seg_d = f"<div class='seg gray' style='height:{hd}px;{op}'>{m['demitidos'] if m['demitidos'] else ''}</div>" if hd > 0 else ""
        cols.append(
            f"<div class='month-col'>"
            f"<div class='stack {style}'>{seg_a}{seg_d}</div>"
            f"<div class='month-label'>{m['label']}</div>"
            f"</div>"
        )
    return "".join(cols)


def _rank_rows(items: list[tuple[str, float, str]], fmt_val) -> str:
    if not items:
        return "<p style='color:#9ca3af;font-size:12px'>Sem dados</p>"
    max_v = max(v for _, v, _ in items) or 1
    return "".join(
        f"<div class='rank-row'>"
        f"<div class='rank-name'>{nome}</div>"
        f"<div class='rank-track'><div class='rank-bar' style='--w:{v/max_v*100:.1f}%'></div></div>"
        f"<div class='rank-value'>{fmt_val(v)}</div>"
        f"</div>"
        for nome, v, _ in items
    )


def _h_bars_motivo(motivos: dict[str, dict]) -> str:
    """Barras horizontais por motivo com split voluntário/involuntário."""
    if not motivos:
        return "<p style='color:#9ca3af;font-size:12px'>Sem dados</p>"
    rows = []
    for motivo, counts in sorted(motivos.items(), key=lambda x: -(x[1]["Voluntário"] + x[1]["Involuntário"])):
        vol = counts.get("Voluntário", 0)
        inv = counts.get("Involuntário", 0)
        total = vol + inv
        pw_inv = inv / total * 100 if total else 0
        pw_vol = vol / total * 100 if total else 0
        seg_inv = f"<div class='h-seg gray' style='width:{pw_inv:.0f}%'>{inv}</div>" if inv else ""
        seg_vol = f"<div class='h-seg red' style='width:{pw_vol:.0f}%'>{vol}</div>" if vol else ""
        rows.append(
            f"<div class='h-row'>"
            f"<div class='h-name'>{motivo}</div>"
            f"<div class='h-track'>{seg_inv}{seg_vol}</div>"
            f"</div>"
        )
    return "".join(rows)


def _h_bars_depto(deptos: dict[str, dict]) -> str:
    if not deptos:
        return "<p style='color:#9ca3af;font-size:12px'>Sem dados</p>"
    rows = []
    for depto, counts in sorted(deptos.items(), key=lambda x: -(x[1]["Voluntário"] + x[1]["Involuntário"])):
        vol = counts.get("Voluntário", 0)
        inv = counts.get("Involuntário", 0)
        total = vol + inv
        pw_inv = inv / total * 100 if total else 0
        pw_vol = vol / total * 100 if total else 0
        seg_inv = f"<div class='h-seg gray' style='width:{pw_inv:.0f}%'>{inv}</div>" if inv else ""
        seg_vol = f"<div class='h-seg red' style='width:{pw_vol:.0f}%'>{vol}</div>" if vol else ""
        rows.append(
            f"<div class='h-row'>"
            f"<div class='h-name'>{depto}</div>"
            f"<div class='h-track small'>{seg_inv}{seg_vol}</div>"
            f"</div>"
        )
    return "".join(rows)


_CSS_TURNOVER = """<style>
:root{
  --red:#e10600;--red-2:#ff3b30;--red-soft:#fff1f0;
  --green:#1f9d62;--amber:#f5a623;--blue:#2f80ed;
  --gray-bar:#8b8b8b;--muted:#6f7378;
  --shadow-soft:0 5px 18px rgba(0,0,0,.05);--radius:22px;
}
*{box-sizing:border-box}
.tv-wrap{font-family:Inter,'Segoe UI',Arial,sans-serif;color:#171717;width:100%}
.topbar{display:grid;grid-template-columns:1fr auto;gap:20px;align-items:center;margin-bottom:16px}
.brand{display:flex;align-items:center;gap:14px}
.brand-mark{width:48px;height:48px;border-radius:16px;background:linear-gradient(145deg,#1c1c1c,#050505);
  display:grid;place-items:center;box-shadow:0 10px 25px rgba(0,0,0,.16);flex-shrink:0}
.brand-mark svg{width:24px;height:24px}
.eyebrow{font-size:11px;font-weight:800;letter-spacing:.18em;text-transform:uppercase;color:var(--red);margin-bottom:3px}
.brand h1{font-size:22px;line-height:1;margin:0;letter-spacing:-.03em}
.brand .subtitle{margin-top:4px;font-size:12px;color:var(--muted)}
.filters{display:flex;gap:10px;align-items:center;flex-wrap:wrap;justify-content:flex-end}
.filter{background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:8px 14px;min-width:130px}
.filter label{display:block;font-size:10px;font-weight:700;color:#9ca3af;text-transform:uppercase;letter-spacing:.08em;margin-bottom:3px}
.filter select{width:100%;border:0;background:transparent;outline:none;color:#111827;font-size:13px;font-weight:600;cursor:pointer}
.hero{background:linear-gradient(135deg,#171717 0%,#0c0c0c 58%,#250000 100%);color:#fff;border-radius:26px;
  padding:22px 24px;display:grid;grid-template-columns:1.15fr .85fr;gap:18px;
  box-shadow:0 20px 46px rgba(0,0,0,.15);position:relative;overflow:hidden;margin-bottom:14px}
.hero:after{content:"";position:absolute;width:290px;height:290px;right:-95px;top:-115px;
  border:56px solid rgba(225,6,0,.2);border-radius:50%}
.hero:before{content:"";position:absolute;width:160px;height:160px;right:250px;bottom:-115px;
  background:rgba(225,6,0,.16);border-radius:50%;filter:blur(2px)}
.hero-left,.hero-kpis{position:relative;z-index:2}
.hero-title{display:flex;justify-content:space-between;align-items:flex-start;gap:14px;margin-bottom:14px}
.hero-title h2{font-size:22px;margin:0 0 4px;letter-spacing:-.03em}
.hero-title p{margin:0;color:#b9b9b9;font-size:12px}
.period-badge{background:rgba(255,255,255,.09);border:1px solid rgba(255,255,255,.13);border-radius:999px;
  padding:7px 11px;font-size:11px;font-weight:800;white-space:nowrap;height:fit-content}
.hero-stats{display:flex;align-items:flex-end;gap:24px;flex-wrap:wrap;margin-top:6px}
.big-number{font-size:52px;font-weight:900;line-height:.9;letter-spacing:-.06em}
.big-caption{color:#b9b9b9;font-size:11px;max-width:160px;line-height:1.35;padding-bottom:4px}
.hero-metric{padding:6px 0}
.hero-metric .mlabel{display:block;color:#b9b9b9;font-size:10px;font-weight:800;text-transform:uppercase;
  letter-spacing:.07em;margin-bottom:4px}
.hero-metric strong{font-size:26px;letter-spacing:-.04em;display:block;line-height:1}
.hero-metric small{color:#d8d8d8;font-size:11px}
.hero-kpis{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;align-items:stretch}
.mini-kpi{background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.1);border-radius:16px;padding:12px;
  display:flex;flex-direction:column;justify-content:space-between;min-height:100px}
.mini-kpi .icon{width:28px;height:28px;border-radius:9px;display:grid;place-items:center;
  background:rgba(255,255,255,.08);font-size:14px}
.mini-kpi strong{font-size:24px;line-height:1;letter-spacing:-.04em}
.mini-kpi span{font-size:9px;color:#bdbdbd;text-transform:uppercase;letter-spacing:.08em;font-weight:800}
.mini-kpi small{color:#e0e0e0;font-size:10px;margin-top:4px}
.mini-kpi.red{background:linear-gradient(160deg,rgba(225,6,0,.24),rgba(255,255,255,.04))}
.mini-kpi.green{background:linear-gradient(160deg,rgba(31,157,98,.18),rgba(255,255,255,.04))}
.mini-kpi.amber{background:linear-gradient(160deg,rgba(245,166,35,.22),rgba(255,255,255,.04))}
.mini-kpi.blue{background:linear-gradient(160deg,rgba(47,128,237,.20),rgba(255,255,255,.04))}
.mini-kpi.slate{background:linear-gradient(160deg,rgba(255,255,255,.12),rgba(255,255,255,.04))}
.grid-main{display:grid;grid-template-columns:1.25fr 1.25fr .9fr;gap:14px;margin-bottom:14px}
.grid-bottom{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px}
.card{background:rgba(255,255,255,.92);border:1px solid rgba(0,0,0,.06);border-radius:var(--radius);
  box-shadow:var(--shadow-soft);padding:16px;display:flex;flex-direction:column;overflow:hidden}
.card-head{display:flex;justify-content:space-between;align-items:flex-start;gap:14px;margin-bottom:12px}
.card-head h3{margin:0;font-size:16px;font-weight:800;letter-spacing:-.02em;color:#1a1a1a}
.card-head p{margin:3px 0 0;color:var(--muted);font-size:12px}
.legend{display:flex;gap:10px;flex-wrap:wrap;align-items:center;color:#666b70;font-size:11px}
.legend .item{display:inline-flex;align-items:center;gap:5px}
.dot{width:10px;height:10px;border-radius:999px;display:inline-block}
.dot.red{background:var(--red)}.dot.gray{background:var(--gray-bar)}
.chart-area{min-height:240px;display:flex;flex:1}
.bars-grid{height:100%;min-height:220px;display:flex;align-items:flex-end;gap:10px;padding:8px 0 0;width:100%}
.month-col{flex:1;min-width:0;display:flex;flex-direction:column;align-items:center;gap:8px}
.stack{width:44px;display:flex;flex-direction:column;justify-content:flex-end;overflow:hidden}
.stack.placeholder{background:linear-gradient(180deg,#f8f8f9,#f1f1f3);border:1px dashed #e2e2e6}
.seg{width:100%;display:grid;place-items:center;color:white;font-size:10px;font-weight:800}
.seg.red{background:var(--red)}.seg.gray{background:var(--gray-bar)}
.month-label{font-size:10px;color:#72767b;font-weight:700}
.line-wrap{height:240px;flex:1}
.line-svg{width:100%;height:100%;display:block}
.gridline{stroke:#ececee;stroke-width:1}
.line{fill:none;stroke:#b1061c;stroke-width:3.5;stroke-linecap:round;stroke-linejoin:round}
.line-point{fill:#fff;stroke:#b1061c;stroke-width:2.5}
.label{font-size:10px;fill:#72767b;font-weight:700}
.h-bars{display:flex;flex-direction:column;gap:8px;padding-top:4px;flex:1;justify-content:space-evenly}
.h-row{display:grid;grid-template-columns:110px 1fr;align-items:center;gap:10px}
.h-name{font-size:11px;color:#666b70;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.h-track{height:40px;display:flex;overflow:hidden;background:#f4f4f5}
.h-track.small{height:32px}
.h-seg{height:100%;display:grid;place-items:center;color:white;font-size:10px;font-weight:800;min-width:20px}
.h-seg.gray{background:var(--gray-bar)}.h-seg.red{background:var(--red)}
.rank-list{display:flex;flex-direction:column;gap:9px;padding-top:4px;flex:1;justify-content:space-evenly}
.rank-row{display:grid;grid-template-columns:130px 1fr auto;gap:9px;align-items:center}
.rank-name{font-size:11px;color:#666b70;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.rank-track{height:16px;border-radius:999px;background:#efeff0;overflow:hidden}
.rank-bar{height:100%;background:linear-gradient(90deg,var(--red),var(--red-2));width:var(--w);min-width:2px}
.rank-value{font-size:11px;font-weight:800;color:#55595d;white-space:nowrap}
.footer-note{margin-top:10px;display:flex;justify-content:space-between;color:#8a8d91;font-size:10px;padding:0 4px}
@media(max-width:1100px){.grid-main{grid-template-columns:1fr 1fr}.grid-bottom{grid-template-columns:repeat(2,1fr)}.hero{grid-template-columns:1fr}}
@media(max-width:700px){.grid-main{grid-template-columns:1fr}.grid-bottom{grid-template-columns:1fr}.hero-kpis{grid-template-columns:repeat(2,1fr)}}
</style>"""


def _build_turnover_html(
    colabs: list[dict],
    ano: int,
    anos_opcoes: list[int],
    todas_empresas: list[str] | None = None,
    todos_deptos: list[str] | None = None,
    empresa_sel: str = "",
    depto_sel: str = "",
    mes_sel: str = "",
) -> str:
    meses = _turnover_mensal(colabs, ano)

    try:
        mes_num = int(mes_sel) if mes_sel else 0
    except ValueError:
        mes_num = 0

    # O mês selecionado vale para tudo, inclusive os gráficos.
    meses_ref = [m for m in meses if not m["futuro"]]
    if mes_num:
        meses_ref = [m for m in meses_ref if m["mes"] == mes_num]

    dem_ano = [c for c in colabs if c["data_demissa"] and c["data_demissa"].year == ano]
    if mes_num:
        dem_ano = [c for c in dem_ano if c["data_demissa"].month == mes_num]

    total_adm  = sum(m["admitidos"] for m in meses_ref)
    total_dem  = sum(m["demitidos"] for m in meses_ref)
    hc_ref     = next((m["headcount"] for m in reversed(meses_ref)), 0) or 1
    turn_total = total_dem / hc_ref * 100

    # desligamentos < 3 meses
    dem_lt3 = [c for c in dem_ano if c["data_adm"] and c["data_demissa"] and
               (c["data_demissa"] - c["data_adm"]).days < 90]

    # turnover voluntário / involuntário
    vol   = sum(1 for c in dem_ano if c["tipo_desligamento"] == "Voluntário")
    invol = sum(1 for c in dem_ano if c["tipo_desligamento"] == "Involuntário")
    turn_vol   = vol   / hc_ref * 100
    turn_invol = invol / hc_ref * 100

    # motivos
    motivos: dict[str, dict] = defaultdict(lambda: defaultdict(int))
    for c in dem_ano:
        motivos[c["motivo_desligamento"]][c["tipo_desligamento"]] += 1

    # turnover por departamento
    deptos_hc: dict[str, int] = defaultdict(int)
    for c in colabs:
        if _is_ativo(c, _eomonth(date(ano, 12, 1))):
            deptos_hc[c["departamento"]] += 1
    deptos_dem: dict[str, int] = defaultdict(int)
    for c in dem_ano:
        deptos_dem[c["departamento"]] += 1
    turn_depto = sorted(
        [(d, deptos_dem[d] / (deptos_hc.get(d, 1)) * 100, "") for d in deptos_dem if d != "Não informado"],
        key=lambda x: -x[1]
    )[:10]

    # desligamentos < 3m por depto
    lt3_depto: dict[str, int] = defaultdict(int)
    for c in dem_lt3:
        lt3_depto[c["departamento"]] += 1
    rank_lt3 = sorted([(d, v, "") for d, v in lt3_depto.items() if d != "Não informado"], key=lambda x: -x[1])[:8]

    # desligamentos por depto + tipo
    depto_tipo: dict[str, dict] = defaultdict(lambda: defaultdict(int))
    for c in dem_ano:
        depto_tipo[c["departamento"]][c["tipo_desligamento"]] += 1

    # unidade
    unidade_tipo: dict[str, dict] = defaultdict(lambda: defaultdict(int))
    for c in dem_ano:
        unidade_tipo[c["unidade"]][c["tipo_desligamento"]] += 1

    # select anos, empresa e departamento
    opts_anos = "".join(
        f"<option value='{a}'{' selected' if a == ano else ''}>{a}</option>"
        for a in anos_opcoes
    )
    emp_opts_tv = "<option value=''>Todas</option>" + "".join(
        f"<option value='{e}'{' selected' if e == (empresa_sel or '').upper() else ''}>{empresa_curta(e)}</option>"
        for e in (todas_empresas or [])
    )
    dep_opts_tv = "<option value=''>Todos</option>" + "".join(
        f"<option value='{d}'{' selected' if d == (depto_sel or '').upper() else ''}>{d.title()}</option>"
        for d in (todos_deptos or [])
    )
    # só meses já ocorridos: mês futuro não tem o que mostrar
    _mes_ops = []
    for m in meses:
        if m["futuro"]:
            continue
        num = m["mes"]
        sel = " selected" if num == mes_num else ""
        _mes_ops.append(f"<option value='{num:02d}'{sel}>{_MES_LABEL[f'{num:02d}']}</option>")
    mes_opts_tv = "<option value=''>Ano todo</option>" + "".join(_mes_ops)

    return f"""<div class="tv-wrap">{_CSS_TURNOVER}

<header class="topbar">
  <div class="brand">
    <div class="brand-mark">
      <svg viewBox="0 0 24 24" fill="none">
        <path d="M5 18V8.5M12 18V4M19 18v-6.5" stroke="#fff" stroke-width="2.2" stroke-linecap="round"/>
        <circle cx="5" cy="6" r="2" fill="#e10600"/>
        <circle cx="12" cy="2.5" r="2" fill="#e10600"/>
        <circle cx="19" cy="9" r="2" fill="#e10600"/>
      </svg>
    </div>
    <div>
      <div class="eyebrow">People Analytics</div>
      <h1>RH · Turnover Executivo</h1>
      <div class="subtitle">Admissões, desligamentos e rotatividade — Porsche Carrera Cup Brasil</div>
    </div>
  </div>
  <div class="filters">
    <form method="get" style="margin:0;display:contents">
      <div class="filter">
        <label>Ano</label>
        <select name="ano" onchange="this.form.submit()" style="width:100%;border:0;background:transparent;outline:none;color:#252525;font-size:13px;font-weight:700;cursor:pointer">
          {opts_anos}
        </select>
      </div>
      <div class="filter">
        <label>Mês</label>
        <select name="mes" onchange="this.form.submit()" style="width:100%;border:0;background:transparent;outline:none;color:#252525;font-size:13px;font-weight:700;cursor:pointer">
          {mes_opts_tv}
        </select>
      </div>
      <div class="filter">
        <label>Empresa</label>
        <select name="empresa" onchange="this.form.submit()" style="width:100%;border:0;background:transparent;outline:none;color:#252525;font-size:13px;font-weight:700;cursor:pointer">
          {emp_opts_tv}
        </select>
      </div>
      <div class="filter">
        <label>Departamento</label>
        <select name="departamento" onchange="this.form.submit()" style="width:100%;border:0;background:transparent;outline:none;color:#252525;font-size:13px;font-weight:700;cursor:pointer">
          {dep_opts_tv}
        </select>
      </div>
    </form>
  </div>
</header>

<section class="hero">
  <div class="hero-left">
    <div class="hero-title">
      <div>
        <h2>Resumo de Turnover</h2>
        <p>Visão do período com foco em movimentação do quadro</p>
      </div>
      <div class="period-badge">Acumulado · {ano}</div>
    </div>
    <div class="hero-stats">
      <div>
        <div class="big-number">{turn_total:.2f}%</div>
        <div class="big-caption">turnover acumulado no período</div>
      </div>
      <div class="hero-metric">
        <span class="mlabel">Turnover voluntário</span>
        <strong>{turn_vol:.2f}%</strong>
        <small>{vol} desligamentos voluntários</small>
      </div>
      <div class="hero-metric">
        <span class="mlabel">Turnover involuntário</span>
        <strong>{turn_invol:.2f}%</strong>
        <small>{invol} desligamentos involuntários</small>
      </div>
    </div>
  </div>
  <div class="hero-kpis">
    <div class="mini-kpi green"><div class="icon">✓</div><strong>{hc_ref:,}</strong><span>Ativos</span><small>Posição atual</small></div>
    <div class="mini-kpi blue"><div class="icon">＋</div><strong>{total_adm:,}</strong><span>Admitidos</span><small>No ano</small></div>
    <div class="mini-kpi red"><div class="icon">↘</div><strong>{total_dem:,}</strong><span>Desligados</span><small>No ano</small></div>
    <div class="mini-kpi amber"><div class="icon">⏱</div><strong>{len(dem_lt3):,}</strong><span>Dem. &lt; 3 meses</span><small>Risco retenção inicial</small></div>
    <div class="mini-kpi slate"><div class="icon">%</div><strong>{turn_total:.2f}%</strong><span>% Turnover</span><small>Dem./Quadro médio</small></div>
    <div class="mini-kpi slate"><div class="icon">◎</div><strong>{turn_vol+turn_invol:.2f}%</strong><span>Turnover V+I</span><small>Voluntário + involuntário</small></div>
  </div>
</section>

<section class="grid-main">
  <article class="card">
    <div class="card-head">
      <div><h3>Admitidos e demitidos por mês</h3><p>Comparativo mensal de entradas e saídas</p></div>
      <div class="legend">
        <span class="item"><span class="dot red"></span> Admitidos</span>
        <span class="item"><span class="dot gray"></span> Demitidos</span>
      </div>
    </div>
    <div class="chart-area"><div class="bars-grid">{_bar_chart_html(meses_ref[-6:])}</div></div>
  </article>

  <article class="card">
    <div class="card-head">
      <div><h3>Turnover % por mês</h3><p>Evolução mensal do indicador</p></div>
      <div class="legend"><span class="item"><span class="dot red"></span> Turnover %</span></div>
    </div>
    <div class="line-wrap">{_turnover_svg(meses_ref[-6:])}</div>
  </article>

  <article class="card">
    <div class="card-head">
      <div><h3>Desligamentos por motivo</h3><p>Voluntário vs involuntário</p></div>
      <div class="legend">
        <span class="item"><span class="dot gray"></span> Involuntário</span>
        <span class="item"><span class="dot red"></span> Voluntário</span>
      </div>
    </div>
    <div class="h-bars">{_h_bars_motivo(motivos)}</div>
  </article>
</section>

<section class="grid-bottom">
  <article class="card">
    <div class="card-head"><div><h3>% Turnover por departamento</h3><p>Áreas com maior índice no período</p></div></div>
    <div class="rank-list">{_rank_rows(turn_depto, lambda v: f"{v:.1f}%")}</div>
  </article>
  <article class="card">
    <div class="card-head"><div><h3>Dem. &lt; 3 meses por departamento</h3><p>Risco de retenção inicial por área</p></div></div>
    <div class="rank-list">{_rank_rows(rank_lt3, lambda v: str(int(v)))}</div>
  </article>
  <article class="card">
    <div class="card-head">
      <div><h3>Desligamentos por depto. e tipo</h3><p>Distribuição por departamento</p></div>
      <div class="legend"><span class="item"><span class="dot gray"></span> Involuntário</span><span class="item"><span class="dot red"></span> Voluntário</span></div>
    </div>
    <div class="h-bars">{_h_bars_depto(depto_tipo)}</div>
  </article>
  <article class="card">
    <div class="card-head">
      <div><h3>Desligamentos por unidade</h3><p>Concentração de saídas por operação</p></div>
      <div class="legend"><span class="item"><span class="dot gray"></span> Involuntário</span><span class="item"><span class="dot red"></span> Voluntário</span></div>
    </div>
    <div class="h-bars">{_h_bars_depto(unidade_tipo)}</div>
  </article>
</section>

<div class="footer-note">
  <span>Base: movimentações do período selecionado. Turnover = desligamentos / quadro médio × 100.</span>
  <span>RH Analytics · Sistema Porsche</span>
</div>
</div>"""


# ─── helpers: db ──────────────────────────────────────────────────────────────

def _db_rows(sql: str, params: dict | None = None) -> list[dict]:
    """Executa SQL bruto e retorna lista de dicts."""
    from app.database import engine
    with engine.connect() as conn:
        result = conn.execute(text(sql), params or {})
        cols = list(result.keys())
        return [dict(zip(cols, row)) for row in result.fetchall()]


# ─── FACILITIES dashboard ─────────────────────────────────────────────────────

_CSS_FAC = """<style>
:root{--bg:#F1F2F4;--surface:#FFF;--ink:#111318;--muted:#69717D;--line:#E1E3E7;
  --black:#0B0B0C;--red:#D50032;--red-soft:#FFF0F3;--green:#078647;--green-soft:#EAF7F0;
  --gold:#C69D4C;--gold-soft:#FFF8E8;}
*{box-sizing:border-box}
.fac-wrap{font-family:Inter,'Segoe UI',Arial,sans-serif;color:var(--ink);width:100%;background:var(--bg);padding:12px 16px}
.fac-topbar{padding:9px 18px;border-radius:0 0 19px 19px;background:var(--black);color:#fff;
  display:flex;align-items:center;justify-content:space-between;margin-bottom:10px}
.fac-brand{color:#D9AE58;font-size:9px;font-weight:900;letter-spacing:2px;text-transform:uppercase}
.fac-title{margin-top:2px;font-size:22px;line-height:1;font-weight:900;letter-spacing:-.8px}
.fac-chips{display:flex;gap:5px}
.fac-chip{min-width:55px;padding:6px 8px;border-radius:9px;text-align:center}
.fac-chip strong{display:block;font-size:13px;line-height:1}
.fac-chip span{display:block;margin-top:2px;color:#B8BBC1;font-size:7px;font-weight:800;text-transform:uppercase}
.fac-chip.cor{background:#421723;color:#FF7795}.fac-chip.pre{background:#123625;color:#43D38B}
.fac-metrics{display:grid;grid-template-columns:repeat(6,1fr);gap:9px;margin-bottom:10px}
.fac-metric{position:relative;padding:11px 13px 9px;border:1px solid var(--line);border-radius:15px;background:var(--surface);overflow:hidden}
.fac-metric:before{content:'';position:absolute;inset:0 auto 0 0;width:4px;background:var(--accent)}
.fac-metric-label{height:25px;color:#555D68;font-size:9px;font-weight:900;letter-spacing:.5px;line-height:1.2;text-transform:uppercase}
.fac-metric-value{font-size:25px;font-weight:900;line-height:1;letter-spacing:-1px}
.fac-metric-unit{color:var(--muted);font-size:9px;font-weight:800}
.fac-metric-footer{margin-top:6px;color:var(--muted);font-size:8px;font-weight:700}
.fac-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:10px}
.fac-grid2{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.fac-card{padding:12px 14px;border:1px solid var(--line);border-radius:17px;background:var(--surface);overflow:hidden}
.fac-card-title{font-size:13px;font-weight:900;margin-bottom:2px}
.fac-card-sub{color:var(--muted);font-size:8px;margin-bottom:8px}
.sb-row{margin-bottom:7px}
.sb-meta{display:flex;justify-content:space-between;align-items:center;gap:7px;margin-bottom:2px}
.sb-name{overflow:hidden;color:#282C32;font-size:8px;font-weight:900;text-overflow:ellipsis;white-space:nowrap;text-transform:uppercase}
.sb-val{flex:none;color:var(--black);font-size:8px;font-weight:900}
.sb-val i{color:var(--muted);font-style:normal;font-weight:700}
.sb-track{overflow:hidden;border-radius:999px;background:#ECEEF1;height:5px}
.sb-bar{height:100%}
.sb-bar.status{background:linear-gradient(90deg,var(--red),#9D001E)}
.sb-bar.center{background:var(--black)}
.sb-bar.type{background:var(--gold)}
.sb-bar.prio-alta{background:linear-gradient(90deg,var(--red),#9D001E)}
.sb-bar.prio-media{background:var(--gold)}
.sb-bar.prio-baixa{background:var(--black)}
.section-lbl{margin:8px 0 4px;color:#555D68;font-size:8px;font-weight:900;letter-spacing:.5px;text-transform:uppercase}
.sup-table{width:100%;border-collapse:collapse;table-layout:fixed}
.sup-table th{height:22px;padding:4px 7px;border-bottom:1px solid var(--line);background:#F7F8F9;color:#666E79;text-align:left;font-size:7px;font-weight:900;letter-spacing:.5px;text-transform:uppercase}
.sup-table td{height:26px;padding:4px 7px;border-bottom:1px solid #ECEEF1;color:#2B2F35;font-size:8px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sup-table tbody tr:hover td{background:#FAFAFB}
.sup-name{display:block;overflow:hidden;color:#111318;font-size:8px;font-weight:900;text-overflow:ellipsis;white-space:nowrap}
.center{text-align:center}.right{text-align:right}
.gold-chip{padding:3px 6px;border-radius:6px;color:#72520F;background:var(--gold-soft);font-size:7px;font-weight:900}
</style>"""


def _fac_small_bars(items: list[tuple], bar_class: str, total: int) -> str:
    if not items:
        return "<p style='color:#9ca3af;font-size:11px'>Sem dados</p>"
    max_v = max(v for _, v in items) or 1
    return "".join(
        f"<div class='sb-row'><div class='sb-meta'>"
        f"<span class='sb-name' title='{nome}'>{nome}</span>"
        f"<span class='sb-val'>{cnt} <i>· {cnt/total*100:.1f}%</i></span>"
        f"</div><div class='sb-track'><div class='sb-bar {bar_class}' style='width:{cnt/max_v*100:.0f}%'></div></div></div>"
        for nome, cnt in items
    )


def _build_facilities_html(tickets: list[dict]) -> str:
    def norm_status(s):
        s = (s or "").strip().lower()
        m = {"completed":"Concluído","concluido":"Concluído","concluído":"Concluído",
             "closed":"Fechado","fechado":"Fechado","pagamento efetuado":"Pagamento efetuado",
             "orçamento":"Orçamento","orcamento":"Orçamento","agendado":"Agendado",
             "execução":"Execução","execucao":"Execução","open":"Em aberto","aberto":"Em aberto"}
        return m.get(s, s.capitalize() if s else "Não informado")

    def norm_priority(p):
        p = (p or "").strip().lower()
        return {"high":"Alta","alta":"Alta","medium":"Média","média":"Média","media":"Média",
                "low":"Baixa","baixa":"Baixa"}.get(p, "Não informada")

    def norm_category(c):
        c = (c or "").strip().lower()
        if "civil" in c and "equip" in c: return "Civil + Equipamentos"
        if "equip" in c: return "Equipamentos"
        if "civil" in c: return "Civil"
        if "hidr" in c: return "Hidráulica"
        if "elétr" in c or "eletr" in c: return "Elétrica"
        return c.capitalize() or "Não informada"

    def norm_unit(u):
        u = (u or "").strip().lower()
        if "stevaux" in u: return "Sede Stevaux"
        if "silva melo" in u: return "Sede nova · Silva Melo"
        return u.capitalize() or "Não informada"

    total = len(tickets) or 1
    finalizados_set = {"concluído","fechado","pagamento efetuado"}
    finalizados = sum(1 for t in tickets if norm_status(t.get("status","")).lower() in finalizados_set)
    pendentes = total - finalizados
    prio_alta = sum(1 for t in tickets if norm_priority(t.get("priority","")) == "Alta")
    corretivas = sum(1 for t in tickets if "corretiva" in (t.get("maintenance_type") or "").lower())
    preventivas = sum(1 for t in tickets if "preventiva" in (t.get("maintenance_type") or "").lower())
    custo = sum(float(t.get("amount") or 0) for t in tickets)
    custo_medio = custo / total

    tempos = []
    for t in tickets:
        ca, co = t.get("created_at"), t.get("completed_at")
        if ca and co:
            try:
                if isinstance(ca, str): ca = datetime.fromisoformat(ca[:19])
                if isinstance(co, str): co = datetime.fromisoformat(co[:19])
                tempos.append((co - ca).total_seconds() / 86400)
            except Exception: pass
    tempo_medio_txt = f"{sum(tempos)/len(tempos):.1f}d" if tempos else "—"

    status_cnt: dict[str, int] = defaultdict(int)
    prio_cnt: dict[str, int] = defaultdict(int)
    cat_cnt: dict[str, int] = defaultdict(int)
    depto_cnt: dict[str, int] = defaultdict(int)
    unit_cnt: dict[str, int] = defaultdict(int)
    sup_data: dict[str, dict] = defaultdict(lambda: {"cnt": 0, "custo": 0.0})

    for t in tickets:
        status_cnt[norm_status(t.get("status",""))] += 1
        prio_cnt[norm_priority(t.get("priority",""))] += 1
        cat_cnt[norm_category(t.get("category",""))] += 1
        depto = (t.get("department") or "Não informado").strip().upper() or "Não informado"
        depto_cnt[depto] += 1
        unit_cnt[norm_unit(t.get("unit",""))] += 1
        sup = (t.get("supplier") or "").strip().upper() or "Não informado"
        if sup == "AGENDADO": sup = "Não informado"
        sup_data[sup]["cnt"] += 1
        sup_data[sup]["custo"] += float(t.get("amount") or 0)

    prio_order = {"Alta": 1, "Média": 2, "Baixa": 3}
    statuses = sorted(status_cnt.items(), key=lambda x: -x[1])
    prios    = sorted(prio_cnt.items(),   key=lambda x: prio_order.get(x[0], 9))
    cats     = sorted(cat_cnt.items(),    key=lambda x: -x[1])
    deptos   = sorted(depto_cnt.items(),  key=lambda x: -x[1])[:4]
    units    = sorted(unit_cnt.items(),   key=lambda x: -x[1])
    sups     = sorted(sup_data.items(),   key=lambda x: -x[1]["custo"])[:6]

    prio_bars = ""
    prio_max = max((v for _,v in prios), default=1) or 1
    for nome, cnt in prios:
        cls = {"Alta":"prio-alta","Média":"prio-media","Baixa":"prio-baixa"}.get(nome,"center")
        prio_bars += (
            f"<div class='sb-row'><div class='sb-meta'>"
            f"<span class='sb-name'>{nome}</span>"
            f"<span class='sb-val'>{cnt} <i>· {cnt/total*100:.1f}%</i></span>"
            f"</div><div class='sb-track'><div class='sb-bar {cls}' style='width:{cnt/prio_max*100:.0f}%'></div></div></div>"
        )

    sup_rows = "".join(
        f"<tr><td><span class='sup-name'>{sup}</span></td>"
        f"<td class='center'>{data['cnt']}</td>"
        f"<td class='right'><span class='gold-chip'>R$ {data['custo']:,.0f}</span></td></tr>"
        for sup, data in sups
    )

    return f"""<div class="fac-wrap">{_CSS_FAC}
<div class="fac-topbar">
  <div><div class="fac-brand">Porsche · Facilities</div><div class="fac-title">Painel de Facilities</div></div>
  <div class="fac-chips">
    <div class="fac-chip cor"><strong>{corretivas}</strong><span>Corretivas</span></div>
    <div class="fac-chip pre"><strong>{preventivas}</strong><span>Preventivas</span></div>
  </div>
</div>
<div class="fac-metrics">
  <div class="fac-metric" style="--accent:#0B0B0C"><div class="fac-metric-label">Total de chamados</div>
    <div style="display:flex;align-items:baseline;gap:6px"><span class="fac-metric-value">{len(tickets)}</span><span class="fac-metric-unit">registros</span></div>
    <div class="fac-metric-footer">Solicitações no período</div></div>
  <div class="fac-metric" style="--accent:#078647"><div class="fac-metric-label">Finalizados</div>
    <div style="display:flex;align-items:baseline;gap:6px"><span class="fac-metric-value">{finalizados}</span><span class="fac-metric-unit">chamados</span></div>
    <div class="fac-metric-footer">Taxa de conclusão: {finalizados/total*100:.1f}%</div></div>
  <div class="fac-metric" style="--accent:#C69D4C"><div class="fac-metric-label">Em aberto</div>
    <div style="display:flex;align-items:baseline;gap:6px"><span class="fac-metric-value">{pendentes}</span><span class="fac-metric-unit">chamados</span></div>
    <div class="fac-metric-footer">{pendentes/total*100:.1f}% do total</div></div>
  <div class="fac-metric" style="--accent:#D50032"><div class="fac-metric-label">Prioridade alta</div>
    <div style="display:flex;align-items:baseline;gap:6px"><span class="fac-metric-value">{prio_alta}</span><span class="fac-metric-unit">chamados</span></div>
    <div class="fac-metric-footer">{prio_alta/total*100:.1f}% dos chamados</div></div>
  <div class="fac-metric" style="--accent:#69717D"><div class="fac-metric-label">Tempo médio</div>
    <div style="display:flex;align-items:baseline;gap:6px"><span class="fac-metric-value">{tempo_medio_txt}</span><span class="fac-metric-unit">dias</span></div>
    <div class="fac-metric-footer">Da abertura à conclusão</div></div>
  <div class="fac-metric" style="--accent:#0B0B0C"><div class="fac-metric-label">Custo total</div>
    <div><span class="fac-metric-value" style="font-size:18px">R$ {custo:,.0f}</span></div>
    <div class="fac-metric-footer">Médio: R$ {custo_medio:,.0f} por chamado</div></div>
</div>
<div class="fac-grid">
  <div class="fac-card"><div class="fac-card-title">Chamados por status</div><div class="fac-card-sub">Quantidade e % do total</div>{_fac_small_bars(statuses,"status",total)}</div>
  <div class="fac-card"><div class="fac-card-title">Prioridade</div><div class="fac-card-sub">Chamados por criticidade</div>{prio_bars}</div>
  <div class="fac-card"><div class="fac-card-title">Chamados por categoria</div><div class="fac-card-sub">Natureza dos problemas</div>{_fac_small_bars(cats,"type",total)}</div>
</div>
<div class="fac-grid2">
  <div class="fac-card">
    <div class="fac-card-title">Departamentos e unidades</div><div class="fac-card-sub">Origem das solicitações</div>
    <div class="section-lbl">Departamentos · top 4</div>{_fac_small_bars(deptos,"center",total)}
    <div class="section-lbl">Unidades</div>{_fac_small_bars(units,"type",total)}
  </div>
  <div class="fac-card">
    <div class="fac-card-title">Custos por fornecedor</div><div class="fac-card-sub">Top 6 por custo total</div>
    <table class="sup-table">
      <thead><tr><th>Fornecedor</th><th class="center">Chamados</th><th class="right">Custo</th></tr></thead>
      <tbody>{sup_rows}</tbody>
    </table>
  </div>
</div>
</div>"""


# ─── TREINAMENTOS dashboard ───────────────────────────────────────────────────

_CSS_TRAIN = """<style>
:root{--bg:#F1F2F4;--surface:#FFF;--ink:#111318;--muted:#69717D;--line:#E1E3E7;
  --black:#0B0B0C;--red:#D50032;--green:#078647;--gold:#C69D4C;--gold-soft:#FFF8E8;}
*{box-sizing:border-box}
.tr-wrap{font-family:Inter,'Segoe UI',Arial,sans-serif;color:var(--ink);width:100%;background:var(--bg);padding:12px 16px}
.tr-chips{display:flex;gap:6px;margin-bottom:10px}
.tr-chip{min-width:74px;padding:7px 11px;border:1px solid var(--line);border-radius:11px;
  background:var(--surface);text-align:left}
.tr-chip strong{display:block;font-size:15px;line-height:1;font-weight:900}
.tr-chip span{display:block;margin-top:3px;color:var(--muted);font-size:7px;font-weight:800;
  letter-spacing:.6px;text-transform:uppercase}
.tr-chip.done strong{color:var(--green)}.tr-chip.pend strong{color:var(--gold)}
.tr-chip.canc strong{color:var(--red)}
.tr-metrics{display:grid;grid-template-columns:repeat(5,1fr);gap:9px;margin-bottom:10px}
.tr-metric{position:relative;padding:11px 13px 9px;border:1px solid var(--line);border-radius:15px;background:var(--surface);overflow:hidden}
.tr-metric:before{content:'';position:absolute;inset:0 auto 0 0;width:4px;background:var(--accent)}
.tr-metric-label{height:25px;color:#555D68;font-size:9px;font-weight:900;letter-spacing:.5px;line-height:1.2;text-transform:uppercase}
.tr-metric-value{font-size:27px;font-weight:900;line-height:1;letter-spacing:-1px}
.tr-metric-footer{margin-top:6px;color:var(--muted);font-size:8px;font-weight:700}
.tr-grid{display:grid;grid-template-columns:1.45fr .9fr .75fr;gap:10px}
.tr-card{padding:12px 14px;border:1px solid var(--line);border-radius:17px;background:var(--surface);overflow:hidden}
.tr-card-title{font-size:13px;font-weight:900;margin-bottom:2px}
.tr-card-sub{color:var(--muted);font-size:8px;margin-bottom:8px}
.train-row{margin-bottom:8px}
.train-meta{display:flex;align-items:flex-end;justify-content:space-between;gap:8px;margin-bottom:2px}
.train-id{min-width:0}
.train-name{overflow:hidden;color:#20242A;font-size:9px;font-weight:900;text-overflow:ellipsis;white-space:nowrap;text-transform:uppercase}
.train-type{color:var(--muted);font-size:7px}
.train-nums{flex:none;display:flex;align-items:baseline;gap:3px;white-space:nowrap}
.train-nums strong{color:var(--red);font-size:10px}.train-nums span{color:var(--muted);font-size:7px}.train-nums b{margin-left:3px;color:var(--black);font-size:8px}
.train-foot{color:var(--muted);font-size:7px;margin-top:1px}
.t-track{overflow:hidden;border-radius:999px;background:#ECEEF1;height:5px;margin-bottom:2px}
.t-bar-red{height:100%;background:linear-gradient(90deg,var(--red),#9D001E)}
.t-bar-blk{height:100%;background:var(--black)}.t-bar-gld{height:100%;background:var(--gold)}
.t-row{margin-bottom:6px}
.t-meta{display:flex;justify-content:space-between;align-items:center;gap:7px;margin-bottom:2px}
.t-name{overflow:hidden;color:#282C32;font-size:8px;font-weight:900;text-overflow:ellipsis;white-space:nowrap;text-transform:uppercase}
.t-val{flex:none;color:var(--black);font-size:8px;font-weight:900}
.t-sub{color:var(--muted);font-size:7px;margin-top:1px}
.ty-row{margin-bottom:10px}
.ty-head{display:flex;align-items:center;justify-content:space-between;gap:6px;margin-bottom:3px}
.ty-name{overflow:hidden;color:#282C32;font-size:8px;font-weight:900;text-overflow:ellipsis;white-space:nowrap;text-transform:uppercase}
.ty-head strong{color:var(--red);font-size:10px}
.ty-foot{color:var(--muted);font-size:7px;margin-top:2px}
.tr-mes{display:grid;grid-template-columns:repeat(6,1fr);align-items:end;gap:10px;height:150px;
  padding-top:6px;border-bottom:1px solid var(--line)}
.tr-mes-col{display:flex;flex-direction:column;justify-content:flex-end;height:100%;text-align:center}
.tr-mes-val{font-size:11px;font-weight:900;color:var(--ink);margin-bottom:3px}
.tr-mes-val.zero{color:var(--muted);font-weight:800}
.tr-mes-bar{width:100%;max-width:52px;margin:0 auto;border-radius:6px 6px 0 0;
  background:linear-gradient(180deg,var(--red),#9D001E);min-height:2px}
.tr-mes-bar.zero{background:#E7E9EC}
.tr-mes-eixo{display:grid;grid-template-columns:repeat(6,1fr);gap:10px;margin-top:5px}
.tr-mes-lbl{text-align:center;font-size:8px;font-weight:900;color:#3B4149;text-transform:uppercase}
.tr-mes-sub{text-align:center;font-size:7px;color:var(--muted);margin-top:1px}
.tr-nota{margin-top:8px;color:var(--muted);font-size:8px}
</style>"""


_MES_LABEL = {
    "01": "Jan", "02": "Fev", "03": "Mar", "04": "Abr", "05": "Mai", "06": "Jun",
    "07": "Jul", "08": "Ago", "09": "Set", "10": "Out", "11": "Nov", "12": "Dez",
}


_COMPETENCIA_RE = re.compile(r"\d{4}-\d{2}")


def _rotulo_mes(m: str) -> str:
    """'2026-03' → 'Mar 2026'."""
    if len(m) >= 7 and m[4] == "-":
        return f"{_MES_LABEL.get(m[5:7], m[5:7])} {m[:4]}"
    return m


_CSS_FILTROS = """<style>
.ind-filtros{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:0 0 14px}
.ind-filtro{background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:8px 14px;min-width:150px}
.ind-filtro label{display:block;font-size:10px;font-weight:700;color:#9ca3af;
  text-transform:uppercase;letter-spacing:.08em;margin-bottom:3px}
.ind-filtro select{width:100%;border:0;background:transparent;outline:none;
  color:#111827;font-size:13px;font-weight:600;cursor:pointer}
.ind-limpar{font-size:12px;color:#6b7280;text-decoration:none;padding:0 4px}
.ind-limpar:hover{color:#111827}
</style>"""


def _filtro_depto_html(acao: str, deptos: list[str], selecionado: str,
                       meses: list[str] | None = None, mes_sel: str = "",
                       ano_sel: str = "", empresas: list[str] | None = None,
                       empresa_sel: str = "") -> str:
    """Barra de filtros dos painéis montados em HTML puro.

    Mesmo visual e mesmos campos do Turnover: Empresa, Departamento, Ano e
    Mês, em cartões brancos lado a lado.
    """
    sel = (selecionado or "").strip().upper()
    opts_dep = "<option value=''>Todos</option>" + "".join(
        f"<option value=\"{d}\"{' selected' if d.upper() == sel else ''}>{d}</option>"
        for d in deptos
    )

    bloco_empresa = ""
    if empresas:
        opts_emp = "<option value=''>Todas</option>" + "".join(
            f"<option value=\"{e}\"{' selected' if e == empresa_sel else ''}>{empresa_curta(e)}</option>"
            for e in empresas
        )
        bloco_empresa = f"""
  <div class="ind-filtro">
    <label>Empresa</label>
    <select name="empresa" onchange="this.form.submit()">{opts_emp}</select>
  </div>"""

    # só entram competências no formato canônico: qualquer outra coisa vira
    # opção ilegível no seletor ("28/0", "09/02/2")
    meses = sorted({m for m in (meses or []) if _COMPETENCIA_RE.fullmatch(m or "")},
                   reverse=True)
    anos = sorted({m[:4] for m in meses}, reverse=True)
    opts_ano = "<option value=''>Todos</option>" + "".join(
        f"<option value=\"{a}\"{' selected' if a == ano_sel else ''}>{a}</option>"
        for a in anos
    )
    # o seletor de mês acompanha o ano escolhido
    meses_vis = [m for m in meses if not ano_sel or m[:4] == ano_sel]
    opts_mes = "<option value=''>Todos</option>" + "".join(
        f"<option value=\"{m}\"{' selected' if m == mes_sel else ''}>{_rotulo_mes(m)}</option>"
        for m in meses_vis
    )

    limpar = (f'<a href="{acao}" class="ind-limpar">✕ Limpar</a>'
              if (selecionado or mes_sel or ano_sel or empresa_sel) else "")

    # Ano e Mês aparecem sempre: escondê-los quando não há dado fazia o filtro
    # sumir justamente na tela vazia, dando a impressão de que não existe.
    return f"""{_CSS_FILTROS}
<form method="get" action="{acao}" class="ind-filtros">{bloco_empresa}
  <div class="ind-filtro">
    <label>Departamento</label>
    <select name="departamento" onchange="this.form.submit()">{opts_dep}</select>
  </div>
  <div class="ind-filtro">
    <label>Ano</label>
    <select name="ano" onchange="this.form.submit()">{opts_ano}</select>
  </div>
  <div class="ind-filtro">
    <label>Mês</label>
    <select name="mes" onchange="this.form.submit()">{opts_mes}</select>
  </div>
  {limpar}
</form>
"""


def _janela_6_meses(ano_sel: str = "") -> list[str]:
    """As 6 competências do gráfico mensal, da mais antiga para a mais recente.

    Termina no mês corrente; com um ano anterior escolhido no filtro, termina
    em dezembro daquele ano, senão o gráfico ficaria vazio.
    """
    hoje = date.today()
    if ano_sel and ano_sel.isdigit() and int(ano_sel) != hoje.year:
        fim_ano, fim_mes = int(ano_sel), 12
    else:
        fim_ano, fim_mes = hoje.year, hoje.month

    janela: list[str] = []
    ano, mes = fim_ano, fim_mes
    for _ in range(6):
        janela.append(f"{ano:04d}-{mes:02d}")
        mes -= 1
        if mes == 0:
            ano, mes = ano - 1, 12
    return list(reversed(janela))


def _serie_6_meses_html(aplicacoes: list[dict], ano_sel: str = "") -> str:
    """Barras de participações e horas nos últimos 6 meses, mês a mês."""
    janela = _janela_6_meses(ano_sel)

    part = {m: 0 for m in janela}
    horas = {m: 0.0 for m in janela}
    for a in aplicacoes:
        comp = a.get("competencia") or ""
        if comp in part:
            part[comp] += 1
            horas[comp] += float(a.get("carga_horaria") or 0)

    teto = max(part.values()) or 1
    colunas, eixo = "", ""
    for m in janela:
        n = part[m]
        # altura mínima visível para o mês sem movimento não sumir da base
        alt = round(n / teto * 100) if n else 0
        vazio = " zero" if not n else ""
        colunas += (f"<div class='tr-mes-col'>"
                    f"<div class='tr-mes-val{vazio}'>{n}</div>"
                    f"<div class='tr-mes-bar{vazio}' style='height:{max(alt, 2)}%'></div></div>")
        eixo += (f"<div><div class='tr-mes-lbl'>{_rotulo_mes(m)}</div>"
                 f"<div class='tr-mes-sub'>{horas[m]:.0f}h</div></div>")

    total = sum(part.values())
    return (f"<div class='tr-mes'>{colunas}</div>"
            f"<div class='tr-mes-eixo'>{eixo}</div>"
            f"<div class='tr-nota'>{total} participação(ões) na janela · "
            f"o filtro de mês não altera este gráfico</div>")


def _build_treinamentos_html(depto_sel: str = "", mes_sel: str = "", ano_sel: str = "",
                             empresa_sel: str = "") -> str:
    try:
        treinamentos = _db_rows("SELECT id_treinamento, nome_treinamento, tipo_treinamento, carga_horaria_padrao, status FROM dho_treinamentos")
        aplicacoes   = _db_rows("SELECT id_aplicacao, id_treinamento, pessoa_nome, centro_custo, data_treinamento, carga_horaria, status FROM dho_treinamento_aplicacoes")
        # o centro de custo pode vir como código; o cadastro da folha dá o
        # nome do departamento e também a empresa dona daquele centro
        try:
            cc_rows = _db_rows("SELECT codigo, nome, empresa FROM folha_centros_custo "
                               "WHERE COALESCE(status, 'Ativo') = 'Ativo'")
            cc_map = {(r["codigo"] or "").strip(): r["nome"] for r in cc_rows}
            cc_emp = {(r["codigo"] or "").strip(): r["empresa"] for r in cc_rows}
        except Exception:
            cc_map, cc_emp = {}, {}
        for a in aplicacoes:
            bruto = (a.get("centro_custo") or "").strip()
            a["departamento"] = cc_map.get(bruto, bruto) or "Não informado"
            a["empresa"] = cc_emp.get(bruto) or ""
    except Exception as e:
        return f"<p style='color:red'>Erro ao carregar dados: {e}</p>"

    todos_deptos = sorted({a["departamento"] for a in aplicacoes
                           if a.get("departamento") and a["departamento"] != "Não informado"})
    # a competência sai do parser central: a data pode estar gravada em
    # qualquer formato e fatiar a string produzia rótulos como "28/0"
    for a in aplicacoes:
        a["competencia"] = competencia_de(a.get("data_treinamento"))
    todos_meses = sorted({a["competencia"] for a in aplicacoes if a["competencia"]},
                         reverse=True)
    todas_empresas = sorted({a["empresa"] for a in aplicacoes if a.get("empresa")})
    if empresa_sel:
        aplicacoes = [a for a in aplicacoes if a.get("empresa") == empresa_sel]
    if depto_sel:
        aplicacoes = [a for a in aplicacoes
                      if (a.get("departamento") or "").upper() == depto_sel.strip().upper()]
    if ano_sel:
        aplicacoes = [a for a in aplicacoes if a["competencia"][:4] == ano_sel]

    # A série mensal é lida antes do filtro de mês: o gráfico existe para
    # mostrar a evolução, e escolher um mês deixaria só uma barra em pé.
    serie_mes_html = _serie_6_meses_html(aplicacoes, ano_sel)

    if mes_sel:
        aplicacoes = [a for a in aplicacoes if a["competencia"] == mes_sel]
    filtro_html = _filtro_depto_html("/indicadores/treinamentos", todos_deptos, depto_sel,
                                     todos_meses, mes_sel, ano_sel,
                                     todas_empresas, empresa_sel)

    ativos     = [t for t in treinamentos if "ativ" in (t.get("status") or "").lower()]
    realizados = sum(1 for a in aplicacoes if "realiz" in (a.get("status") or "").lower())
    pendentes  = sum(1 for a in aplicacoes if any(k in (a.get("status") or "").lower() for k in ("pend","program","agend")))
    cancelados = sum(1 for a in aplicacoes if "cancel" in (a.get("status") or "").lower())

    pessoas_unicas = len({a["pessoa_nome"] for a in aplicacoes if a.get("pessoa_nome")})
    horas_total    = sum(float(a.get("carga_horaria") or 0) for a in aplicacoes)
    carga_media    = horas_total / len(aplicacoes) if aplicacoes else 0
    centros        = len({a["centro_custo"] for a in aplicacoes if a.get("centro_custo")})

    t_data: dict[int, dict] = {}
    for t in ativos:
        t_data[t["id_treinamento"]] = {"nome": t["nome_treinamento"], "tipo": t["tipo_treinamento"],
                                        "apl": 0, "pessoas": set(), "horas": 0.0}
    for a in aplicacoes:
        tid = a["id_treinamento"]
        if tid in t_data:
            t_data[tid]["apl"] += 1
            if a.get("pessoa_nome"): t_data[tid]["pessoas"].add(a["pessoa_nome"])
            t_data[tid]["horas"] += float(a.get("carga_horaria") or 0)

    sorted_tr = sorted(t_data.values(), key=lambda x: (-x["apl"], -x["horas"]))
    max_apl = max((x["apl"] for x in sorted_tr), default=1) or 1

    train_rows = ""
    for x in sorted_tr:
        w = x["apl"] / max_apl * 100
        tnome, ttipo = x["nome"], x["tipo"]
        train_rows += (
            f"<div class='train-row'><div class='train-meta'>"
            f"<div class='train-id'><div class='train-name' title='{tnome}'>{tnome}</div><div class='train-type'>{ttipo}</div></div>"
            f"<div class='train-nums'><strong>{x['apl']}</strong><span>participações</span><b>{x['horas']:.1f}h</b></div>"
            f"</div><div class='t-track'><div class='t-bar-red' style='width:{w:.0f}%'></div></div>"
            f"<div class='train-foot'>{len(x['pessoas'])} pessoas únicas</div></div>"
        )

    centro_data: dict[str, dict] = defaultdict(lambda: {"apl": 0, "pessoas": set(), "horas": 0.0})
    for a in aplicacoes:
        cc = a.get("centro_custo") or "Não informado"
        centro_data[cc]["apl"] += 1
        if a.get("pessoa_nome"): centro_data[cc]["pessoas"].add(a["pessoa_nome"])
        centro_data[cc]["horas"] += float(a.get("carga_horaria") or 0)
    top_centros = sorted(centro_data.items(), key=lambda x: -x[1]["horas"])[:7]
    max_hc = max((d["horas"] for _,d in top_centros), default=1) or 1

    centro_bars = ""
    for cc, d in top_centros:
        if not d["apl"]: continue
        w = d["horas"] / max_hc * 100
        centro_bars += (
            f"<div class='t-row'><div class='t-meta'><span class='t-name' title='{cc}'>{cc}</span>"
            f"<span class='t-val'>{d['horas']:.1f}h</span></div>"
            f"<div class='t-track'><div class='t-bar-blk' style='width:{w:.0f}%'></div></div>"
            f"<div class='t-sub'>{len(d['pessoas'])} pessoas · {d['apl']} participações</div></div>"
        )

    tipo_data: dict[str, dict] = defaultdict(lambda: {"tr": 0, "apl": 0, "horas": 0.0})
    tipo_map = {t["id_treinamento"]: t["tipo_treinamento"] for t in treinamentos}
    for t in treinamentos:
        tipo_data[t["tipo_treinamento"]]["tr"] += 1
    for a in aplicacoes:
        tp = tipo_map.get(a["id_treinamento"], "Sem tipo")
        tipo_data[tp]["apl"] += 1
        tipo_data[tp]["horas"] += float(a.get("carga_horaria") or 0)
    sorted_tipos = sorted(tipo_data.items(), key=lambda x: -x[1]["apl"])
    max_apl_tipo = max((d["apl"] for _,d in sorted_tipos), default=1) or 1

    tipo_rows = ""
    for tp, d in sorted_tipos:
        if not d["tr"]: continue
        w = d["apl"] / max_apl_tipo * 100
        tipo_rows += (
            f"<div class='ty-row'><div class='ty-head'>"
            f"<span class='ty-name' title='{tp}'>{tp}</span><strong>{d['apl']}</strong></div>"
            f"<div class='t-track'><div class='t-bar-gld' style='width:{w:.0f}%'></div></div>"
            f"<div class='ty-foot'>{d['tr']} treinamentos · {d['horas']:.1f}h</div></div>"
        )

    return f"""{filtro_html}<div class="tr-wrap">{_CSS_TRAIN}
<div class="tr-chips">
  <div class="tr-chip done"><strong>{realizados}</strong><span>Realizados</span></div>
  <div class="tr-chip pend"><strong>{pendentes}</strong><span>Pendentes</span></div>
  <div class="tr-chip canc"><strong>{cancelados}</strong><span>Cancelados</span></div>
</div>
<div class="tr-metrics">
  <div class="tr-metric" style="--accent:#0B0B0C"><div class="tr-metric-label">Treinamentos ativos</div>
    <div style="display:flex;align-items:baseline;gap:6px"><span class="tr-metric-value">{len(ativos)}</span><span style="color:var(--muted);font-size:9px;font-weight:800">cadastrados</span></div>
    <div class="tr-metric-footer">Catálogo disponível</div></div>
  <div class="tr-metric" style="--accent:#078647"><div class="tr-metric-label">Pessoas treinadas</div>
    <div style="display:flex;align-items:baseline;gap:6px"><span class="tr-metric-value">{pessoas_unicas}</span><span style="color:var(--muted);font-size:9px;font-weight:800">únicas</span></div>
    <div class="tr-metric-footer">Sem duplicar participantes</div></div>
  <div class="tr-metric" style="--accent:#C69D4C"><div class="tr-metric-label">Horas aplicadas</div>
    <div style="display:flex;align-items:baseline;gap:6px"><span class="tr-metric-value">{horas_total:.1f}</span><span style="color:var(--muted);font-size:9px;font-weight:800">horas</span></div>
    <div class="tr-metric-footer">Soma das cargas horárias</div></div>
  <div class="tr-metric" style="--accent:#69717D"><div class="tr-metric-label">Carga horária média</div>
    <div style="display:flex;align-items:baseline;gap:6px"><span class="tr-metric-value">{carga_media:.1f}</span><span style="color:var(--muted);font-size:9px;font-weight:800">horas</span></div>
    <div class="tr-metric-footer">Média por participação</div></div>
  <div class="tr-metric" style="--accent:#0B0B0C"><div class="tr-metric-label">Centros atendidos</div>
    <div style="display:flex;align-items:baseline;gap:6px"><span class="tr-metric-value">{centros}</span><span style="color:var(--muted);font-size:9px;font-weight:800">centros</span></div>
    <div class="tr-metric-footer">Áreas com treinamento</div></div>
</div>
<div class="tr-card" style="margin-bottom:10px">
  <div class="tr-card-title">Participações por mês</div>
  <div class="tr-card-sub">Últimos 6 meses · quantidade de participações e horas aplicadas</div>
  {serie_mes_html}
</div>
<div class="tr-grid">
  <div class="tr-card"><div class="tr-card-title">Resultado por treinamento</div><div class="tr-card-sub">Participações, pessoas e horas aplicadas</div>{train_rows}</div>
  <div class="tr-card"><div class="tr-card-title">Horas por centro de custo</div><div class="tr-card-sub">7 centros com maior carga aplicada</div>{centro_bars}</div>
  <div class="tr-card"><div class="tr-card-title">Participações por tipo</div><div class="tr-card-sub">Distribuição do catálogo</div>{tipo_rows}</div>
</div>
</div>"""


# ─── VAGAS dashboard ──────────────────────────────────────────────────────────

_CSS_VAGAS = """<style>
:root{--bg:#F1F2F4;--surface:#FFF;--ink:#111318;--muted:#69717D;--line:#E1E3E7;
  --black:#0B0B0C;--red:#D50032;--red-soft:#FFF0F3;--green:#078647;--green-soft:#EAF7F0;--gold:#C69D4C;}
*{box-sizing:border-box}
.vg-wrap{font-family:Inter,'Segoe UI',Arial,sans-serif;color:var(--ink);width:100%;background:var(--bg);padding:12px 16px}
.vg-metrics{display:grid;grid-template-columns:repeat(6,1fr);gap:9px;margin-bottom:10px}
.vg-metric{position:relative;padding:11px 13px 9px;border:1px solid var(--line);border-radius:15px;background:var(--surface);overflow:hidden}
.vg-metric:before{content:'';position:absolute;inset:0 auto 0 0;width:4px;background:var(--accent)}
.vg-metric-label{height:28px;color:#555D68;font-size:9px;font-weight:900;letter-spacing:.5px;line-height:1.25;text-transform:uppercase}
.vg-metric-value{font-size:29px;font-weight:900;line-height:1;letter-spacing:-1px}
.vg-metric-unit{color:var(--muted);font-size:10px;font-weight:700}
.vg-metric-footer{margin-top:6px;font-size:8px;font-weight:700;color:var(--muted)}
.vg-danger{color:var(--red)}.vg-success{color:var(--green)}
.vg-content{display:grid;grid-template-columns:1.7fr .8fr;gap:12px}
.vg-card{padding:12px 14px;border:1px solid var(--line);border-radius:17px;background:var(--surface);overflow:hidden}
.vg-card-title{font-size:15px;font-weight:900;line-height:1.15;margin-bottom:2px}
.vg-card-sub{color:var(--muted);font-size:10px;margin-bottom:8px}
.vg-legend{display:flex;flex-wrap:wrap;align-items:center;gap:11px;color:var(--muted);font-size:9px;margin-bottom:8px}
.vg-legend-item{display:inline-flex;align-items:center;gap:5px}
.vg-dot{width:8px;height:8px;border-radius:3px;background:var(--black)}.vg-dot.red{background:var(--red)}
.vg-area-grid{display:grid;grid-template-columns:repeat(2,1fr);column-gap:22px;row-gap:6px}
.bar-item{min-width:0}
.bar-meta{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:4px}
.bar-name{overflow:hidden;color:#272B31;font-size:10px;font-weight:800;text-overflow:ellipsis;white-space:nowrap;text-transform:uppercase}
.bar-val{flex:none;color:var(--muted);font-size:9px;font-weight:800;white-space:nowrap}
.bar-val b{color:var(--red)}
.track{height:8px;display:flex;overflow:hidden;border-radius:99px;background:#ECEEF1}
.seg{height:100%;min-width:0}.seg.open{background:var(--red)}.seg.done{background:var(--black)}
.vg-side{display:grid;grid-template-rows:1fr 1fr;gap:10px}
.vg-side .bar-meta{margin-bottom:2px}
.vg-side .bar-name{font-size:9px;line-height:11px}.vg-side .bar-val{font-size:8px}
.vg-side .track{height:6px}
.vg-side-label{margin:0 0 5px;color:var(--muted);font-size:8px;font-weight:900;letter-spacing:1px;text-transform:uppercase}
.vg-profile-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.vg-mes{display:grid;grid-template-columns:repeat(6,1fr);align-items:end;gap:10px;height:150px;
  padding-top:6px;border-bottom:1px solid var(--line)}
.vg-mes-col{display:flex;flex-direction:column;justify-content:flex-end;height:100%;text-align:center}
.vg-mes-val{font-size:11px;font-weight:900;color:var(--ink);margin-bottom:3px}
.vg-mes-val.zero{color:var(--muted);font-weight:800}
.vg-mes-bar{display:flex;flex-direction:column;width:100%;max-width:52px;margin:0 auto;
  overflow:hidden;border-radius:6px 6px 0 0;min-height:2px}
.vg-mes-bar.zero{background:#E7E9EC}
.vg-mes-seg{display:block;width:100%}
.vg-mes-seg.open{background:var(--red)}.vg-mes-seg.done{background:var(--black)}
.vg-mes-eixo{display:grid;grid-template-columns:repeat(6,1fr);gap:10px;margin-top:5px}
.vg-mes-lbl{text-align:center;font-size:8px;font-weight:900;color:#3B4149;text-transform:uppercase}
.vg-mes-sub{text-align:center;font-size:7px;color:var(--muted);margin-top:1px}
.vg-nota{margin-top:8px;color:var(--muted);font-size:8px}
</style>"""


def _serie_vagas_6_meses_html(vagas: list[dict], ano_sel: str = "") -> str:
    """Vagas abertas mês a mês nos últimos 6 meses, separando o que já fechou.

    A barra usa a data de abertura: mostra quanto entrou em cada mês e quanto
    daquilo já foi preenchido, nas mesmas cores do resto do painel.
    """
    janela = _janela_6_meses(ano_sel)
    abertas = {m: 0 for m in janela}
    concluidas = {m: 0 for m in janela}

    for v in vagas:
        comp = v.get("competencia") or ""
        if comp not in abertas:
            continue
        qtd = v.get("qtd_vagas") or 1
        if "conclu" in (v.get("status") or "").lower():
            concluidas[comp] += qtd
        else:
            abertas[comp] += qtd

    totais = {m: abertas[m] + concluidas[m] for m in janela}
    teto = max(totais.values()) or 1

    colunas, eixo = "", ""
    for m in janela:
        n = totais[m]
        if n:
            h_ab = round(abertas[m] / n * 100)
            # sem mês vazio: os segmentos é que dão cor à barra
            segs = (f"<span class='vg-mes-seg done' style='height:{100 - h_ab}%'></span>"
                    f"<span class='vg-mes-seg open' style='height:{h_ab}%'></span>")
            barra = f"<div class='vg-mes-bar' style='height:{max(round(n / teto * 100), 2)}%'>{segs}</div>"
        else:
            barra = "<div class='vg-mes-bar zero' style='height:2%'></div>"
        colunas += (f"<div class='vg-mes-col'>"
                    f"<div class='vg-mes-val{'' if n else ' zero'}'>{n}</div>{barra}</div>")
        eixo += (f"<div><div class='vg-mes-lbl'>{_rotulo_mes(m)}</div>"
                 f"<div class='vg-mes-sub'>A {abertas[m]} · C {concluidas[m]}</div></div>")

    return (f"<div class='vg-legend'>"
            f"<span class='vg-legend-item'><i class='vg-dot red'></i>Aberto</span>"
            f"<span class='vg-legend-item'><i class='vg-dot'></i>Concluído</span></div>"
            f"<div class='vg-mes'>{colunas}</div>"
            f"<div class='vg-mes-eixo'>{eixo}</div>"
            f"<div class='vg-nota'>{sum(totais.values())} vaga(s) abertas na janela · "
            f"o filtro de mês não altera este gráfico</div>")


def _build_vagas_html(depto_sel: str = "", mes_sel: str = "", ano_sel: str = "") -> str:
    try:
        vagas = _db_rows(
            """SELECT v.id_vaga, v.qtd_vagas, v.status, v.tipo_vaga, v.tipo_recrutamento,
                      v.data_abertura, v.data_conclusao,
                      COALESCE(NULLIF(TRIM(d.nome_departamento), ''), '') AS nome_departamento
               FROM dho_vagas v
               LEFT JOIN dho_departamentos d ON d.id_departamento = v.id_departamento"""
        )
    except Exception as e:
        return f"<p style='color:red'>Erro ao carregar dados: {e}</p>"

    todos_deptos = sorted({
        (v.get("nome_departamento") or "").strip()
        for v in vagas if (v.get("nome_departamento") or "").strip()
    })
    # a competência sai do parser central: a data pode estar gravada em
    # qualquer formato e fatiar a string produzia rótulos como "28/0"
    for v in vagas:
        v["competencia"] = competencia_de(v.get("data_abertura"))
    todos_meses = sorted({v["competencia"] for v in vagas if v["competencia"]},
                         reverse=True)
    if depto_sel:
        vagas = [v for v in vagas
                 if (v.get("nome_departamento") or "").strip().upper() == depto_sel.strip().upper()]
    if ano_sel:
        vagas = [v for v in vagas if v["competencia"][:4] == ano_sel]

    # a série mensal é lida antes do filtro de mês: escolher um mês deixaria
    # uma única barra em pé e o gráfico existe para mostrar a evolução
    serie_mes_html = _serie_vagas_6_meses_html(vagas, ano_sel)

    if mes_sel:
        vagas = [v for v in vagas if v["competencia"] == mes_sel]
    filtro_html = _filtro_depto_html("/indicadores/vagas", todos_deptos, depto_sel,
                                     todos_meses, mes_sel, ano_sel)

    hoje_d = date.today()

    def is_aberta(v): return "abert" in (v.get("status") or "").lower()
    def is_concluida(v): return "conclu" in (v.get("status") or "").lower()

    parse_date_vg = data_para_date

    total_vagas = sum(v.get("qtd_vagas") or 1 for v in vagas) or 1
    abertas     = sum((v.get("qtd_vagas") or 1) for v in vagas if is_aberta(v))
    concluidas  = sum((v.get("qtd_vagas") or 1) for v in vagas if is_concluida(v))
    pct_abertas    = abertas / total_vagas * 100
    pct_concluidas = concluidas / total_vagas * 100

    dias_vals = [(parse_date_vg(v.get("data_conclusao")) - parse_date_vg(v.get("data_abertura"))).days
                 for v in vagas if is_concluida(v) and parse_date_vg(v.get("data_abertura")) and parse_date_vg(v.get("data_conclusao"))]
    dias_medios = sum(dias_vals) / len(dias_vals) if dias_vals else 0

    abertas_mais30 = sum(
        (v.get("qtd_vagas") or 1) for v in vagas
        if is_aberta(v) and parse_date_vg(v.get("data_abertura")) and (hoje_d - parse_date_vg(v.get("data_abertura"))).days > 30
    )

    depto_data: dict[str, dict] = defaultdict(lambda: {"a": 0, "c": 0})
    for v in vagas:
        dep = v.get("nome_departamento") or "Não informado"
        if is_aberta(v):    depto_data[dep]["a"] += v.get("qtd_vagas") or 1
        if is_concluida(v): depto_data[dep]["c"] += v.get("qtd_vagas") or 1
    deptos_sorted = sorted(depto_data.items(), key=lambda x: -(x[1]["a"]+x[1]["c"]))
    max_dep = max((d["a"]+d["c"] for _,d in deptos_sorted), default=1) or 1

    area_bars = "".join(
        f"<div class='bar-item'><div class='bar-meta'><span class='bar-name'>{dep}</span>"
        f"<span class='bar-val'><b>A {d['a']}</b> · C {d['c']}</span></div><div class='track'>"
        f"<span class='seg open' style='width:{d['a']/max_dep*100:.0f}%'></span>"
        f"<span class='seg done' style='width:{d['c']/max_dep*100:.0f}%'></span></div></div>"
        for dep, d in deptos_sorted
    )

    faixas = [("0 a 7 dias",0,7),("8 a 15 dias",8,15),("16 a 30 dias",16,30),
              ("31 a 60 dias",31,60),("61 a 90 dias",61,90),("Acima de 90 dias",91,999999)]
    faixa_data: dict[str, dict] = defaultdict(lambda: {"a": 0, "c": 0})
    for v in vagas:
        da = parse_date_vg(v.get("data_abertura"))
        if not da: continue
        dc = parse_date_vg(v.get("data_conclusao")) or hoje_d
        dias = (dc - da).days
        for nome, mn, mx in faixas:
            if mn <= dias <= mx:
                if is_aberta(v):    faixa_data[nome]["a"] += v.get("qtd_vagas") or 1
                if is_concluida(v): faixa_data[nome]["c"] += v.get("qtd_vagas") or 1
                break
    max_fx = max((d["a"]+d["c"] for d in faixa_data.values()), default=1) or 1

    faixa_bars = "".join(
        f"<div class='bar-item' style='margin-bottom:4px'><div class='bar-meta'>"
        f"<span class='bar-name' style='text-transform:none'>{nome}</span>"
        f"<span class='bar-val'><b>A {faixa_data[nome]['a']}</b> · C {faixa_data[nome]['c']}</span></div>"
        f"<div class='track'><span class='seg open' style='width:{faixa_data[nome]['a']/max_fx*100:.0f}%'></span>"
        f"<span class='seg done' style='width:{faixa_data[nome]['c']/max_fx*100:.0f}%'></span></div></div>"
        for nome, _, __ in faixas if faixa_data.get(nome, {"a":0,"c":0})["a"] + faixa_data.get(nome, {"a":0,"c":0})["c"] > 0
    )

    def _profile_bars(field: str):
        cnt: dict[str, dict] = defaultdict(lambda: {"a":0,"c":0})
        for v in vagas:
            val = (v.get(field) or "Sem tipo").strip()
            if is_aberta(v):    cnt[val]["a"] += v.get("qtd_vagas") or 1
            if is_concluida(v): cnt[val]["c"] += v.get("qtd_vagas") or 1
        sorted_v = sorted(cnt.items(), key=lambda x: -(x[1]["a"]+x[1]["c"]))
        mv = max((d["a"]+d["c"] for _,d in sorted_v), default=1) or 1
        return "".join(
            f"<div class='bar-item' style='margin-bottom:8px'><div class='bar-meta'>"
            f"<span class='bar-name'>{nome}</span>"
            f"<span class='bar-val'><b>A {d['a']}</b> · C {d['c']}</span></div><div class='track'>"
            f"<span class='seg open' style='width:{d['a']/mv*100:.0f}%'></span>"
            f"<span class='seg done' style='width:{d['c']/mv*100:.0f}%'></span></div></div>"
            for nome, d in sorted_v if d["a"]+d["c"]
        )

    return f"""{filtro_html}<div class="vg-wrap">{_CSS_VAGAS}
<div class="vg-metrics">
  <div class="vg-metric" style="--accent:#0B0B0C"><div class="vg-metric-label">Total de vagas</div>
    <div style="display:flex;align-items:baseline;gap:6px"><span class="vg-metric-value">{total_vagas}</span><span class="vg-metric-unit">vagas</span></div>
    <div class="vg-metric-footer">Registros no período</div></div>
  <div class="vg-metric" style="--accent:#D50032"><div class="vg-metric-label">Vagas abertas</div>
    <div style="display:flex;align-items:baseline;gap:6px"><span class="vg-metric-value vg-danger">{abertas}</span><span class="vg-metric-unit">{pct_abertas:.1f}%</span></div>
    <div class="vg-metric-footer">Em andamento</div></div>
  <div class="vg-metric" style="--accent:#078647"><div class="vg-metric-label">Vagas concluídas</div>
    <div style="display:flex;align-items:baseline;gap:6px"><span class="vg-metric-value vg-success">{concluidas}</span><span class="vg-metric-unit">vagas</span></div>
    <div class="vg-metric-footer">Preenchidas</div></div>
  <div class="vg-metric" style="--accent:#078647"><div class="vg-metric-label">Taxa de conclusão</div>
    <div style="display:flex;align-items:baseline;gap:6px"><span class="vg-metric-value vg-success">{pct_concluidas:.1f}%</span></div>
    <div class="vg-metric-footer">Concluídas / Total</div></div>
  <div class="vg-metric" style="--accent:#C69D4C"><div class="vg-metric-label">Dias médios para concluir</div>
    <div style="display:flex;align-items:baseline;gap:6px"><span class="vg-metric-value">{dias_medios:.0f}</span><span class="vg-metric-unit">dias</span></div>
    <div class="vg-metric-footer">Da abertura à conclusão</div></div>
  <div class="vg-metric" style="--accent:#D50032"><div class="vg-metric-label">Abertas há mais de 30 dias</div>
    <div style="display:flex;align-items:baseline;gap:6px"><span class="vg-metric-value vg-danger">{abertas_mais30}</span><span class="vg-metric-unit">atenção</span></div>
    <div class="vg-metric-footer">Requer acompanhamento</div></div>
</div>
<div class="vg-card" style="margin-bottom:12px">
  <div class="vg-card-title">Vagas por mês</div>
  <div class="vg-card-sub">Últimos 6 meses · vagas abertas em cada mês, pela data de abertura</div>
  {serie_mes_html}
</div>
<div class="vg-content">
  <div class="vg-card">
    <div class="vg-card-title">Vagas por área</div><div class="vg-card-sub">Distribuição completa por departamento</div>
    <div class="vg-legend">
      <span class="vg-legend-item"><i class="vg-dot red"></i>Aberto</span>
      <span class="vg-legend-item"><i class="vg-dot"></i>Concluído</span>
    </div>
    <div class="vg-area-grid">{area_bars}</div>
  </div>
  <div class="vg-side">
    <div class="vg-card"><div class="vg-card-title">Faixa de dias</div><div class="vg-card-sub">Tempo de permanência no processo</div>{faixa_bars}</div>
    <div class="vg-card"><div class="vg-card-title">Perfil das vagas</div><div class="vg-card-sub">Tipo e origem do recrutamento</div>
      <div class="vg-profile-grid">
        <div><div class="vg-side-label">Tipo de vaga</div>{_profile_bars("tipo_vaga")}</div>
        <div><div class="vg-side-label">Recrutamento</div>{_profile_bars("tipo_recrutamento")}</div>
      </div>
    </div>
  </div>
</div>
</div>"""


# ─── folha de pagamento · indicadores ────────────────────────────────────────

_CSS_FOLHA = """<style>
*{box-sizing:border-box;margin:0;padding:0}
:root{--red:#e10600;--red2:#c50000;--bg:#f4f5f7;--card:#fff;--border:rgba(0,0,0,.07);
  --text:#1a1a1a;--muted:#6b7280;--radius:14px;--shadow:0 1px 4px rgba(0,0,0,.08)}
.fl-wrap{font-family:'Inter',system-ui,sans-serif;background:var(--bg);color:var(--text);
  min-height:100vh;padding:0}
/* topbar */
.fl-top{display:grid;grid-template-columns:1fr auto;align-items:center;gap:16px;
  background:linear-gradient(135deg,#0a0a0a 0%,#1c1c1c 100%);color:#fff;
  padding:18px 24px}
.fl-brand{display:flex;align-items:center;gap:14px}
.fl-mark{width:40px;height:40px;background:var(--red);border-radius:10px;display:grid;place-items:center}
.fl-eyebrow{font-size:10px;font-weight:800;letter-spacing:.12em;color:#9ca3af;text-transform:uppercase}
.fl-title{font-size:18px;font-weight:800;letter-spacing:-.03em}
.fl-sub{font-size:11px;color:#9ca3af;margin-top:1px}
.fl-filters{display:flex;gap:12px;flex-wrap:wrap}
.fl-filter{background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.12);
  border-radius:10px;padding:6px 14px;min-width:160px}
.fl-filter label{display:block;font-size:9px;font-weight:800;letter-spacing:.1em;color:#9ca3af;
  text-transform:uppercase;margin-bottom:2px}
.fl-filter select{width:100%;border:0;background:transparent;outline:none;color:#fff;
  font-size:13px;font-weight:700;cursor:pointer}
.fl-filter select option{color:#111}
/* kpi row */
.fl-kpi-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;
  padding:16px 24px 0}
.fl-kpi{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);
  padding:16px 18px;box-shadow:var(--shadow)}
.fl-kpi-icon{width:30px;height:30px;border-radius:9px;display:grid;place-items:center;
  background:#f3f4f6;font-size:14px;margin-bottom:8px}
.fl-kpi-val{font-size:26px;font-weight:900;letter-spacing:-.04em;line-height:1}
.fl-kpi-label{font-size:10px;color:var(--muted);font-weight:700;text-transform:uppercase;
  letter-spacing:.06em;margin-top:4px}
.fl-kpi.accent{background:linear-gradient(160deg,rgba(225,6,0,.12),#fff)}
/* content grid */
.fl-grid{display:grid;grid-template-columns:1.6fr .4fr;gap:14px;padding:14px 24px 0}
.fl-grid-full{display:grid;grid-template-columns:1fr;gap:14px;padding:14px 24px 0}
.fl-grid-half{display:grid;grid-template-columns:1fr 1fr;gap:14px;padding:14px 24px 0}
.fl-card{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);
  padding:18px;box-shadow:var(--shadow)}
.fl-card-title{font-size:14px;font-weight:700;letter-spacing:-.02em;margin-bottom:4px}
.fl-card-sub{font-size:11px;color:var(--muted);margin-bottom:14px}
/* bars */
.fl-bar-row{display:grid;grid-template-columns:minmax(120px,1fr) 2fr auto;align-items:center;
  gap:8px;margin-bottom:9px}
.fl-bar-label{font-size:11px;color:#54575b;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.fl-bar-track{height:7px;background:#ececee;border-radius:999px;overflow:hidden}
.fl-bar-fill{height:100%;border-radius:999px;background:linear-gradient(90deg,var(--red),var(--red2));
  min-width:2px}
.fl-bar-val{font-size:10px;color:#555;white-space:nowrap;text-align:right}
.fl-bar-val b{font-size:11px;color:#111}
/* tabela simples */
.fl-table{width:100%;border-collapse:collapse;font-size:11px}
.fl-table th{background:#f7f7f8;font-size:10px;font-weight:800;text-transform:uppercase;
  letter-spacing:.06em;color:var(--muted);padding:7px 10px;text-align:left;
  border-bottom:1px solid var(--border)}
.fl-table td{padding:7px 10px;border-bottom:1px solid #f0f1f3;vertical-align:top}
.fl-table tr:hover td{background:#fafafa}
.fl-table .num{text-align:right;font-variant-numeric:tabular-nums;font-weight:700}
.fl-table .prov{color:#078647;font-weight:700}
.fl-table .desc{color:var(--red);font-weight:700}
/* holerite individual */
.fl-slip{background:#fff;border:1px solid var(--border);border-radius:var(--radius);padding:20px}
.fl-slip-head{display:grid;grid-template-columns:1fr auto;gap:16px;margin-bottom:16px;
  padding-bottom:12px;border-bottom:2px solid var(--red)}
.fl-slip-name{font-size:18px;font-weight:800;letter-spacing:-.03em}
.fl-slip-meta{font-size:11px;color:var(--muted);margin-top:4px}
.fl-slip-badge{background:var(--red);color:#fff;border-radius:8px;padding:6px 12px;
  font-size:11px;font-weight:700;text-align:center}
.fl-slip-grid{display:grid;grid-template-columns:1fr 1fr;gap:0}
.fl-slip-col-head{font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:.08em;
  color:var(--muted);padding:6px 0;border-bottom:1px solid var(--border)}
.fl-slip-row{display:grid;grid-template-columns:1fr auto;font-size:11px;padding:5px 0;
  border-bottom:1px solid #f5f5f7}
.fl-slip-row:last-child{border-bottom:0}
.fl-slip-row .cod{color:var(--muted);font-size:10px;margin-right:6px}
.fl-slip-totals{display:grid;grid-template-columns:1fr 1fr 1fr;gap:0;margin-top:12px;
  padding-top:12px;border-top:2px solid var(--border)}
.fl-slip-total-item{text-align:center;padding:8px}
.fl-slip-total-label{font-size:10px;font-weight:800;text-transform:uppercase;color:var(--muted);
  letter-spacing:.08em}
.fl-slip-total-val{font-size:18px;font-weight:900;letter-spacing:-.04em;margin-top:4px}
.fl-slip-total-val.prov{color:#078647}
.fl-slip-total-val.desc{color:var(--red)}
.fl-slip-total-val.liq{color:#1a1a1a}
/* lista holerites */
.fl-emp-card{background:var(--card);border:1px solid var(--border);border-radius:12px;
  padding:14px 16px;display:grid;grid-template-columns:1fr auto;align-items:center;
  gap:12px;margin-bottom:8px;box-shadow:var(--shadow)}
.fl-emp-name{font-size:13px;font-weight:700}
.fl-emp-meta{font-size:10px;color:var(--muted);margin-top:2px}
.fl-emp-nums{display:flex;gap:14px;text-align:right}
.fl-emp-num{font-size:11px;color:var(--muted)}
.fl-emp-num b{display:block;font-size:13px;color:var(--text);font-weight:800}
.fl-emp-num b.prov{color:#078647}
.fl-emp-num b.desc{color:var(--red)}
.fl-footer{padding:12px 24px 20px;display:flex;justify-content:space-between;
  color:#8a8d91;font-size:10px}
@media(max-width:900px){.fl-grid{grid-template-columns:1fr}.fl-grid-half{grid-template-columns:1fr}
  .fl-kpi-row{grid-template-columns:repeat(2,1fr)}}
</style>"""


def _fmt_brl(v) -> str:
    """Formata valor em BRL pt-BR."""
    try:
        f = float(v or 0)
        return f"R$ {f:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "—"


def _folha_query_filters(empresa: str, competencia: str) -> tuple[str, dict]:
    """Retorna cláusula WHERE e params para os filtros comuns de folha."""
    clauses, params = [], {}
    if empresa:
        clauses.append("fa.empresa_nome = :empresa")
        params["empresa"] = empresa
    if competencia:
        clauses.append("ff.competencia = :competencia")
        params["competencia"] = competencia
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def _build_folha_visao_custo_html(
    empresa: str,
    competencia: str,
    todas_empresas: list[str],
    todas_competencias: list[str],
) -> str:
    where, params = _folha_query_filters(empresa, competencia)

    # KPIs principais da folha
    kpi_rows = _db_rows(f"""
        SELECT
            COALESCE(SUM(ff.total_proventos),0) AS total_proventos,
            COALESCE(SUM(ff.total_descontos),0) AS total_descontos,
            COALESCE(SUM(ff.liquido),0)          AS total_liquido,
            COALESCE(SUM(ff.salario),0)          AS total_salario,
            COALESCE(SUM(ff.valor_fgts),0)       AS total_fgts,
            COALESCE(SUM(ff.base_inss),0)        AS total_base_inss,
            COUNT(DISTINCT ff.id_funcionario)    AS qtd_func
        FROM folha_funcionarios ff
        JOIN folha_arquivos fa ON fa.id_arquivo = ff.id_arquivo
        {where}
    """, params)
    k = kpi_rows[0] if kpi_rows else {}
    prov   = float(k.get("total_proventos") or 0)
    desc   = float(k.get("total_descontos") or 0)
    liquido = float(k.get("total_liquido") or 0)
    salario = float(k.get("total_salario") or 0)
    fgts   = float(k.get("total_fgts") or 0)
    qtd_func = int(k.get("qtd_func") or 0)

    # Evolução por competência (últimas 6 competências, ordenado)
    evol_rows = _db_rows("""
        SELECT ff.competencia,
               SUM(ff.total_proventos) AS prov,
               SUM(ff.liquido) AS liq,
               COUNT(DISTINCT ff.id_funcionario) AS hc
        FROM folha_funcionarios ff
        JOIN folha_arquivos fa ON fa.id_arquivo = ff.id_arquivo
        GROUP BY ff.competencia
        ORDER BY ff.competencia DESC
        LIMIT 6
    """)
    evol_rows = list(reversed(evol_rows))  # cronológico

    # Custo por empresa
    emp_rows = _db_rows("""
        SELECT fa.empresa_nome, SUM(ff.total_proventos) AS prov
        FROM folha_funcionarios ff
        JOIN folha_arquivos fa ON fa.id_arquivo = ff.id_arquivo
        GROUP BY fa.empresa_nome
        ORDER BY prov DESC
        LIMIT 8
    """)
    emp_max = max((float(r["prov"] or 0) for r in emp_rows), default=1) or 1

    # Rubricas mais relevantes (top proventos + descontos)
    rub_rows = _db_rows(f"""
        SELECT fr.descricao, fr.tipo,
               SUM(fr.valor) AS total
        FROM folha_rubricas fr
        JOIN folha_funcionarios ff ON ff.id_funcionario = fr.id_funcionario
        JOIN folha_arquivos fa ON fa.id_arquivo = ff.id_arquivo
        {where}
        GROUP BY fr.descricao, fr.tipo
        ORDER BY total DESC
        LIMIT 12
    """, params)

    # Seletores
    emp_opts  = "<option value=''>Todas as empresas</option>" + "".join(
        f"<option value='{e}'{' selected' if e == empresa else ''}>{empresa_curta(e)}</option>"
        for e in todas_empresas
    )
    comp_opts = "<option value=''>Todas as competências</option>" + "".join(
        f"<option value='{c}'{' selected' if c == competencia else ''}>{c}</option>"
        for c in todas_competencias
    )

    # SVG evolução por competência
    def _evol_svg() -> str:
        if not evol_rows:
            return "<p style='color:var(--muted);font-size:12px'>Sem dados</p>"
        vals = [float(r["prov"] or 0) for r in evol_rows]
        vmax = max(vals) * 1.1 or 1
        W, top, bot, padl = 540, 30, 150, 50
        n = len(vals)
        xs = [padl + i * (W - padl - 20) / max(n - 1, 1) for i in range(n)]
        def fy(v): return bot - (v / vmax) * (bot - top)
        pts = [(xs[i], fy(v)) for i, v in enumerate(vals)]
        line = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        area = f"M{pts[0][0]:.1f},{bot} " + " ".join(f"L{x:.1f},{y:.1f}" for x, y in pts) + f" L{pts[-1][0]:.1f},{bot} Z"
        circles = "".join(f"<circle cx='{x:.1f}' cy='{y:.1f}' r='4' fill='#fff' stroke='var(--red)' stroke-width='2.5'/>" for x, y in pts)
        labels  = "".join(f"<text x='{xs[i]:.1f}' y='{bot+18}' text-anchor='middle' font-size='9' fill='#7b7e83' font-weight='700'>{r['competencia'][-7:]}</text>" for i, r in enumerate(evol_rows))
        vals_t  = "".join(f"<text x='{pts[i][0]:.1f}' y='{pts[i][1]-8:.1f}' text-anchor='middle' font-size='9' fill='#242424' font-weight='900'>{_fmt_brl(v)}</text>" for i, v in enumerate(vals))
        return f"""<svg viewBox="0 0 {W} {bot+40}" style="width:100%;display:block">
          <defs><linearGradient id="eg" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="var(--red)" stop-opacity=".18"/><stop offset="100%" stop-color="var(--red)" stop-opacity="0"/></linearGradient></defs>
          <path d="{area}" fill="url(#eg)"/>
          <path d="{line}" fill="none" stroke="var(--red)" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round"/>
          {circles}{labels}{vals_t}
        </svg>"""

    # Barras de rubricas
    rub_html = ""
    rub_prov = [(r["descricao"], float(r["total"] or 0)) for r in rub_rows if r["tipo"] == "P"][:6]
    rub_desc = [(r["descricao"], float(r["total"] or 0)) for r in rub_rows if r["tipo"] == "D"][:6]
    rp_max = max((v for _, v in rub_prov), default=1) or 1
    rd_max = max((v for _, v in rub_desc), default=1) or 1
    for lbl, val in rub_prov:
        pct = val / rp_max * 100
        rub_html += f"<div class='fl-bar-row'><div class='fl-bar-label'>{lbl}</div><div class='fl-bar-track'><div class='fl-bar-fill' style='width:{pct:.1f}%;background:linear-gradient(90deg,#078647,#05a353)'></div></div><div class='fl-bar-val'><b>{_fmt_brl(val)}</b></div></div>"
    rd_html = ""
    for lbl, val in rub_desc:
        pct = val / rd_max * 100
        rd_html += f"<div class='fl-bar-row'><div class='fl-bar-label'>{lbl}</div><div class='fl-bar-track'><div class='fl-bar-fill' style='width:{pct:.1f}%'></div></div><div class='fl-bar-val'><b>{_fmt_brl(val)}</b></div></div>"

    # Barras empresas
    def _emp_bar(r) -> str:
        enome = r["empresa_nome"] or "—"
        eprov = float(r["prov"] or 0)
        epct  = eprov / emp_max * 100
        return (
            f"<div class='fl-bar-row'>"
            f"<div class='fl-bar-label'>{enome}</div>"
            f"<div class='fl-bar-track'><div class='fl-bar-fill' style='width:{epct:.1f}%'></div></div>"
            f"<div class='fl-bar-val'><b>{_fmt_brl(eprov)}</b></div>"
            f"</div>"
        )
    emp_html = "".join(_emp_bar(r) for r in emp_rows)

    return f"""<div class="fl-wrap">{_CSS_FOLHA}

<div class="fl-top">
  <div class="fl-brand">
    <div class="fl-mark">💰</div>
    <div>
      <div class="fl-eyebrow">Folha de Pagamento</div>
      <div class="fl-title">Visão Custo Empresa</div>
      <div class="fl-sub">Porsche Carrera Cup Brasil &amp; Sprint Challenge Brasil</div>
    </div>
  </div>
  <div class="fl-filters">
    <form method="get" style="margin:0;display:contents">
      <div class="fl-filter"><label>Empresa</label>
        <select name="empresa" onchange="this.form.submit()">{emp_opts}</select>
      </div>
      <div class="fl-filter"><label>Competência</label>
        <select name="competencia" onchange="this.form.submit()">{comp_opts}</select>
      </div>
    </form>
  </div>
</div>

<div class="fl-kpi-row">
  <div class="fl-kpi accent">
    <div class="fl-kpi-icon">💰</div>
    <div class="fl-kpi-val">{_fmt_brl(prov)}</div>
    <div class="fl-kpi-label">Custo total</div>
  </div>
  <div class="fl-kpi">
    <div class="fl-kpi-icon">📋</div>
    <div class="fl-kpi-val">{_fmt_brl(salario)}</div>
    <div class="fl-kpi-label">Custo salário</div>
  </div>
  <div class="fl-kpi">
    <div class="fl-kpi-icon">🏦</div>
    <div class="fl-kpi-val">{_fmt_brl(fgts)}</div>
    <div class="fl-kpi-label">FGTS</div>
  </div>
  <div class="fl-kpi">
    <div class="fl-kpi-icon">↘</div>
    <div class="fl-kpi-val" style="color:var(--red)">{_fmt_brl(desc)}</div>
    <div class="fl-kpi-label">Descontos</div>
  </div>
  <div class="fl-kpi">
    <div class="fl-kpi-icon">✓</div>
    <div class="fl-kpi-val" style="color:#078647">{_fmt_brl(liquido)}</div>
    <div class="fl-kpi-label">Líquido total</div>
  </div>
  <div class="fl-kpi">
    <div class="fl-kpi-icon">👥</div>
    <div class="fl-kpi-val">{qtd_func:,}</div>
    <div class="fl-kpi-label">Colaboradores</div>
  </div>
</div>

<div class="fl-grid" style="padding-top:14px">
  <div class="fl-card">
    <div class="fl-card-title">Custo por competência</div>
    <div class="fl-card-sub">Total de proventos por período (últimas 6 competências)</div>
    {_evol_svg()}
  </div>
  <div class="fl-card">
    <div class="fl-card-title">Custo por empresa</div>
    <div class="fl-card-sub">Ranking de custo total por CNPJ</div>
    {emp_html or "<p style='color:var(--muted);font-size:12px'>Sem dados</p>"}
  </div>
</div>

<div class="fl-grid-half" style="padding-top:14px">
  <div class="fl-card">
    <div class="fl-card-title">Principais proventos</div>
    <div class="fl-card-sub">Rubricas de provento mais expressivas</div>
    {rub_html or "<p style='color:var(--muted);font-size:12px'>Sem dados</p>"}
  </div>
  <div class="fl-card">
    <div class="fl-card-title">Principais descontos</div>
    <div class="fl-card-sub">Rubricas de desconto mais expressivas</div>
    {rd_html or "<p style='color:var(--muted);font-size:12px'>Sem dados</p>"}
  </div>
</div>

<div class="fl-footer">
  <span>Base: folha de pagamento importada no sistema.</span>
  <span>Folha Analytics · Sistema Porsche</span>
</div>
</div>"""


def _build_folha_holerite_html(
    empresa: str,
    competencia: str,
    colaborador: str,
    todas_empresas: list[str],
    todas_competencias: list[str],
    todos_colaboradores: list[str],
) -> str:
    where, params = _folha_query_filters(empresa, competencia)
    if colaborador:
        where = (where + " AND ff.nome = :colab") if where else "WHERE ff.nome = :colab"
        params["colab"] = colaborador

    # Dados do funcionário selecionado
    func_rows = _db_rows(f"""
        SELECT ff.*, fa.empresa_nome, fa.cnpj
        FROM folha_funcionarios ff
        JOIN folha_arquivos fa ON fa.id_arquivo = ff.id_arquivo
        {where}
        LIMIT 1
    """, params)

    # Rubricas do funcionário
    rub_rows = []
    if func_rows:
        func = func_rows[0]
        rub_rows = _db_rows("""
            SELECT codigo, descricao, referencia, valor, tipo
            FROM folha_rubricas
            WHERE id_funcionario = :id
            ORDER BY tipo DESC, valor DESC
        """, {"id": func["id_funcionario"]})

    # Evolução salário (últimas 6 competências)
    evol_sal = []
    if colaborador:
        evol_sal = _db_rows("""
            SELECT ff.competencia, ff.salario, ff.total_proventos, ff.liquido
            FROM folha_funcionarios ff
            JOIN folha_arquivos fa ON fa.id_arquivo = ff.id_arquivo
            WHERE ff.nome = :colab
            ORDER BY ff.competencia ASC
            LIMIT 6
        """, {"colab": colaborador})

    # Seletores
    emp_opts  = "<option value=''>Todas</option>" + "".join(
        f"<option value='{e}'{' selected' if e == empresa else ''}>{empresa_curta(e)}</option>"
        for e in todas_empresas
    )
    comp_opts = "<option value=''>Última</option>" + "".join(
        f"<option value='{c}'{' selected' if c == competencia else ''}>{c}</option>"
        for c in todas_competencias
    )
    colab_opts = "<option value=''>— selecione —</option>" + "".join(
        f"<option value='{n}'{' selected' if n == colaborador else ''}>{n.title()}</option>"
        for n in todos_colaboradores
    )

    # HTML do holerite
    slip_html = ""
    if func_rows:
        f = func_rows[0]
        prov_rows = [r for r in rub_rows if r["tipo"] == "P"]
        desc_rows = [r for r in rub_rows if r["tipo"] == "D"]
        prov_items = "".join(
            f"<div class='fl-slip-row'><span><span class='cod'>{r['codigo']}</span>{r['descricao']}</span><span>{_fmt_brl(r['valor'])}</span></div>"
            for r in prov_rows
        )
        desc_items = "".join(
            f"<div class='fl-slip-row'><span><span class='cod'>{r['codigo']}</span>{r['descricao']}</span><span>{_fmt_brl(r['valor'])}</span></div>"
            for r in desc_rows
        )
        slip_html = f"""<div class="fl-slip">
  <div class="fl-slip-head">
    <div>
      <div class="fl-slip-name">{(f.get('nome') or '').title()}</div>
      <div class="fl-slip-meta">{f.get('cargo','—')} · {f.get('departamento','—')} · Matrícula {f.get('matricula','—')}</div>
      <div class="fl-slip-meta">CPF {f.get('cpf','—')} · Admissão {f.get('data_admissao','—')} · {f.get('vinculo','—')}</div>
    </div>
    <div class="fl-slip-badge">
      {f.get('competencia','—')}<br>
      <small>{(f.get('empresa_nome') or '').title()}</small>
    </div>
  </div>
  <div class="fl-slip-grid">
    <div style="padding-right:16px;border-right:1px solid var(--border)">
      <div class="fl-slip-col-head" style="color:#078647">Proventos</div>
      {prov_items or "<div style='color:var(--muted);font-size:11px;padding:8px 0'>Nenhum</div>"}
    </div>
    <div style="padding-left:16px">
      <div class="fl-slip-col-head" style="color:var(--red)">Descontos</div>
      {desc_items or "<div style='color:var(--muted);font-size:11px;padding:8px 0'>Nenhum</div>"}
    </div>
  </div>
  <div class="fl-slip-totals">
    <div class="fl-slip-total-item">
      <div class="fl-slip-total-label">Total proventos</div>
      <div class="fl-slip-total-val prov">{_fmt_brl(f.get('total_proventos'))}</div>
    </div>
    <div class="fl-slip-total-item" style="border-left:1px solid var(--border);border-right:1px solid var(--border)">
      <div class="fl-slip-total-label">Total descontos</div>
      <div class="fl-slip-total-val desc">{_fmt_brl(f.get('total_descontos'))}</div>
    </div>
    <div class="fl-slip-total-item">
      <div class="fl-slip-total-label">Valor líquido</div>
      <div class="fl-slip-total-val liq">{_fmt_brl(f.get('liquido'))}</div>
    </div>
  </div>
</div>"""

    return f"""<div class="fl-wrap">{_CSS_FOLHA}

<div class="fl-top">
  <div class="fl-brand">
    <div class="fl-mark">🧾</div>
    <div>
      <div class="fl-eyebrow">Folha de Pagamento</div>
      <div class="fl-title">Holerite por Colaborador</div>
      <div class="fl-sub">Visualização individual de proventos e descontos</div>
    </div>
  </div>
  <div class="fl-filters">
    <form method="get" style="margin:0;display:contents">
      <div class="fl-filter"><label>Empresa</label>
        <select name="empresa" onchange="this.form.submit()">{emp_opts}</select>
      </div>
      <div class="fl-filter"><label>Competência</label>
        <select name="competencia" onchange="this.form.submit()">{comp_opts}</select>
      </div>
      <div class="fl-filter" style="min-width:220px"><label>Colaborador</label>
        <select name="colaborador" onchange="this.form.submit()">{colab_opts}</select>
      </div>
    </form>
  </div>
</div>

<div class="fl-grid-full" style="padding-top:16px">
  {slip_html or "<div class='fl-card' style='color:var(--muted);text-align:center;padding:48px'>Selecione um colaborador para visualizar o holerite.</div>"}
</div>

<div class="fl-footer">
  <span>Base: folha importada no sistema.</span>
  <span>Folha Analytics · Sistema Porsche</span>
</div>
</div>"""


def _build_folha_lista_html(
    empresa: str,
    competencia: str,
    todas_empresas: list[str],
    todas_competencias: list[str],
) -> str:
    where, params = _folha_query_filters(empresa, competencia)

    func_rows = _db_rows(f"""
        SELECT ff.nome, ff.matricula, ff.cargo, ff.departamento,
               ff.competencia, ff.salario, ff.total_proventos,
               ff.total_descontos, ff.liquido, fa.empresa_nome
        FROM folha_funcionarios ff
        JOIN folha_arquivos fa ON fa.id_arquivo = ff.id_arquivo
        {where}
        ORDER BY fa.empresa_nome, ff.competencia DESC, ff.nome
        LIMIT 500
    """, params)

    rows_html = "".join(
        f"<tr>"
        f"<td>{(r.get('empresa_nome') or '').title()}</td>"
        f"<td>{r.get('competencia','—')}</td>"
        f"<td>{(r.get('nome') or '').title()}</td>"
        f"<td>{r.get('matricula','—')}</td>"
        f"<td>{(r.get('cargo') or '—').title()}</td>"
        f"<td>{r.get('departamento','—')}</td>"
        f"<td class='num'>{_fmt_brl(r.get('salario'))}</td>"
        f"<td class='num prov'>{_fmt_brl(r.get('total_proventos'))}</td>"
        f"<td class='num desc'>{_fmt_brl(r.get('total_descontos'))}</td>"
        f"<td class='num'>{_fmt_brl(r.get('liquido'))}</td>"
        f"</tr>"
        for r in func_rows
    )

    emp_opts  = "<option value=''>Todas</option>" + "".join(
        f"<option value='{e}'{' selected' if e == empresa else ''}>{empresa_curta(e)}</option>"
        for e in todas_empresas
    )
    comp_opts = "<option value=''>Todas</option>" + "".join(
        f"<option value='{c}'{' selected' if c == competencia else ''}>{c}</option>"
        for c in todas_competencias
    )

    return f"""<div class="fl-wrap">{_CSS_FOLHA}

<div class="fl-top">
  <div class="fl-brand">
    <div class="fl-mark">📋</div>
    <div>
      <div class="fl-eyebrow">Folha de Pagamento</div>
      <div class="fl-title">Holerite · Lista</div>
      <div class="fl-sub">Tabela consolidada de todos os colaboradores</div>
    </div>
  </div>
  <div class="fl-filters">
    <form method="get" style="margin:0;display:contents">
      <div class="fl-filter"><label>Empresa</label>
        <select name="empresa" onchange="this.form.submit()">{emp_opts}</select>
      </div>
      <div class="fl-filter"><label>Competência</label>
        <select name="competencia" onchange="this.form.submit()">{comp_opts}</select>
      </div>
    </form>
  </div>
</div>

<div class="fl-grid-full" style="padding-top:16px;overflow-x:auto">
  <div class="fl-card" style="padding:0;overflow:hidden">
    <div style="overflow-x:auto">
      <table class="fl-table">
        <thead><tr>
          <th>Empresa</th><th>Competência</th><th>Colaborador</th>
          <th>Matrícula</th><th>Cargo</th><th>Depto</th>
          <th class="num">Salário</th><th class="num">Proventos</th>
          <th class="num">Descontos</th><th class="num">Líquido</th>
        </tr></thead>
        <tbody>
          {rows_html or "<tr><td colspan='10' style='text-align:center;color:var(--muted);padding:32px'>Nenhum registro encontrado.</td></tr>"}
        </tbody>
      </table>
    </div>
  </div>
</div>

<div class="fl-footer">
  <span>Exibindo até 500 registros. Base: folha importada no sistema.</span>
  <span>Folha Analytics · Sistema Porsche</span>
</div>
</div>"""


def _build_folha_custo_colab_html(
    empresa: str,
    competencia: str,
    todas_empresas: list[str],
    todas_competencias: list[str],
) -> str:
    where, params = _folha_query_filters(empresa, competencia)

    func_rows = _db_rows(f"""
        SELECT ff.nome, ff.cargo, ff.departamento,
               ff.salario, ff.total_proventos, ff.total_descontos, ff.liquido,
               ff.valor_fgts, ff.base_inss, fa.empresa_nome, ff.competencia
        FROM folha_funcionarios ff
        JOIN folha_arquivos fa ON fa.id_arquivo = ff.id_arquivo
        {where}
        ORDER BY ff.total_proventos DESC
        LIMIT 100
    """, params)

    max_prov = max((float(r.get("total_proventos") or 0) for r in func_rows), default=1) or 1

    cards = ""
    for r in func_rows:
        prov = float(r.get("total_proventos") or 0)
        desc = float(r.get("total_descontos") or 0)
        liq  = float(r.get("liquido") or 0)
        pct  = prov / max_prov * 100
        emp_n = (r.get("empresa_nome") or "").title()
        nome  = (r.get("nome") or "").title()
        cargo = (r.get("cargo") or "—").title()
        depto = r.get("departamento") or "—"
        cards += f"""<div class="fl-emp-card">
  <div>
    <div class="fl-emp-name">{nome}</div>
    <div class="fl-emp-meta">{cargo} · {depto} · {emp_n} · {r.get('competencia','')}</div>
    <div style="margin-top:6px"><div style="height:4px;background:#ececee;border-radius:999px;overflow:hidden">
      <div style="height:100%;width:{pct:.1f}%;background:linear-gradient(90deg,var(--red),var(--red2));border-radius:999px"></div>
    </div></div>
  </div>
  <div class="fl-emp-nums">
    <div class="fl-emp-num"><b class="prov">{_fmt_brl(prov)}</b>Proventos</div>
    <div class="fl-emp-num"><b class="desc">{_fmt_brl(desc)}</b>Descontos</div>
    <div class="fl-emp-num"><b>{_fmt_brl(liq)}</b>Líquido</div>
  </div>
</div>"""

    emp_opts  = "<option value=''>Todas</option>" + "".join(
        f"<option value='{e}'{' selected' if e == empresa else ''}>{empresa_curta(e)}</option>"
        for e in todas_empresas
    )
    comp_opts = "<option value=''>Todas</option>" + "".join(
        f"<option value='{c}'{' selected' if c == competencia else ''}>{c}</option>"
        for c in todas_competencias
    )

    return f"""<div class="fl-wrap">{_CSS_FOLHA}

<div class="fl-top">
  <div class="fl-brand">
    <div class="fl-mark">👤</div>
    <div>
      <div class="fl-eyebrow">Folha de Pagamento</div>
      <div class="fl-title">Custo por Colaborador</div>
      <div class="fl-sub">Ranking de custo total por pessoa</div>
    </div>
  </div>
  <div class="fl-filters">
    <form method="get" style="margin:0;display:contents">
      <div class="fl-filter"><label>Empresa</label>
        <select name="empresa" onchange="this.form.submit()">{emp_opts}</select>
      </div>
      <div class="fl-filter"><label>Competência</label>
        <select name="competencia" onchange="this.form.submit()">{comp_opts}</select>
      </div>
    </form>
  </div>
</div>

<div class="fl-grid-full" style="padding-top:16px">
  <div class="fl-card" style="padding:12px">
    {cards or "<div style='color:var(--muted);text-align:center;padding:40px'>Nenhum dado encontrado. Importe folhas de pagamento no módulo Folha.</div>"}
  </div>
</div>

<div class="fl-footer">
  <span>Exibindo até 100 colaboradores, ordenado por custo total. Base: folha importada.</span>
  <span>Folha Analytics · Sistema Porsche</span>
</div>
</div>"""


# ─── rotas ────────────────────────────────────────────────────────────────────

@router.get("/sem-acesso")
def sem_acesso(request: Request, modulo: str = ""):
    nomes = {
        "dho": "DHO / RH",
        "folha": "Folha de Pagamento",
        "facilities": "Facilities",
        "autonomos": "Autônomos",
    }
    return templates.TemplateResponse("sem_acesso.html", {
        "request": request,
        "modulo": modulo,
        "modulo_nome": nomes.get(modulo, modulo or "este módulo"),
    })


@router.get("/indicadores")
def indicadores_home(request: Request):
    return templates.TemplateResponse("indicadores/index.html", {"request": request})


@router.get("/indicadores/turnover")
def turnover(request: Request, ano: str = "", empresa: str = "", departamento: str = "",
             mes: str = ""):
    erro = None
    dash_html = ""

    hoje = date.today()
    anos_opcoes = list(range(hoje.year, hoje.year - 5, -1))
    try:
        ano_int = int(ano) if ano else hoje.year
    except ValueError:
        ano_int = hoje.year
    if ano_int not in anos_opcoes:
        ano_int = hoje.year

    try:
        rows = _fetch_feedz("rel_colab_77")
        todos_colabs = _normalizar_colabs(rows)
        todas_empresas_tv = sorted({c["empresa"] for c in todos_colabs} - {"Não informado"})
        todos_deptos_tv = sorted({c["departamento"] for c in todos_colabs} - {"Não informado"})
        colabs = todos_colabs
        if empresa:
            colabs = [c for c in colabs if c["empresa"] == empresa.upper()]
        if departamento:
            colabs = [c for c in colabs if c["departamento"] == departamento.upper()]
        dash_html = _build_turnover_html(
            colabs, ano_int, anos_opcoes,
            todas_empresas_tv, todos_deptos_tv, empresa, departamento, mes,
        )
    except Exception as exc:
        erro = f"Erro ao buscar dados do Feedz: {exc}"

    return templates.TemplateResponse("indicadores/turnover.html", {
        "request": request,
        "dash_html": dash_html,
        "erro": erro,
    })


@router.get("/indicadores/headcount")
def headcount(request: Request, mes: str = "", empresa: str = "", departamento: str = ""):
    erro = None
    dash_html = ""

    if mes:
        try:
            ref_base = datetime.strptime(mes + "-01", "%Y-%m-%d").date()
        except ValueError:
            ref_base = date.today()
    else:
        ref_base = date.today()
    ref = _eomonth(ref_base)
    mes_sel = mes or f"{ref_base.year}-{ref_base.month:02d}"

    hoje = date.today()
    meses_opcoes: list[tuple[str, str]] = []
    for i in range(11, -1, -1):
        ano, m = hoje.year, hoje.month - i
        while m <= 0:
            m += 12; ano -= 1
        meses_opcoes.append((f"{ano}-{m:02d}", _mes_label(date(ano, m, 1))))

    try:
        rows = _fetch_feedz("rel_colab_77")
        todos_colabs = _normalizar_colabs(rows)
        # Listas para dropdowns (antes do filtro)
        todas_empresas = sorted({c["empresa"] for c in todos_colabs} - {"Não informado"})
        todos_deptos = sorted({c["departamento"] for c in todos_colabs} - {"Não informado"})
        # Aplica filtros
        colabs = todos_colabs
        if empresa:
            colabs = [c for c in colabs if c["empresa"] == empresa.upper()]
        if departamento:
            colabs = [c for c in colabs if c["departamento"] == departamento.upper()]
        dash_html = _build_headcount_html(
            colabs, ref, meses_opcoes, mes_sel,
            todas_empresas, todos_deptos, empresa, departamento,
        )
    except Exception as exc:
        erro = f"Erro ao buscar dados do Feedz: {exc}"

    return templates.TemplateResponse("indicadores/headcount.html", {
        "request": request,
        "dash_html": dash_html,
        "erro": erro,
    })


@router.get("/indicadores/facilities")
def facilities_dash(request: Request):
    erro = None
    dash_html = ""
    try:
        from app.routers.facilities import (
            DEFAULT_CACHE_CSV_PATH, preparar_chamados, ler_complementos,
        )
        from app.integrations.google_sheets.sync import maintenance_tickets
        from app.database import get_db
        import csv

        tickets: list[dict] = []
        if os.path.exists(DEFAULT_CACHE_CSV_PATH):
            with open(DEFAULT_CACHE_CSV_PATH, "r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                tickets = [row for row in reader]
        else:
            from app.database import engine as _eng
            from sqlalchemy import select as _sel
            with _eng.connect() as conn:
                rows = conn.execute(_sel(maintenance_tickets)).fetchall()
                cols = maintenance_tickets.columns.keys()
                tickets = [dict(zip(cols, r)) for r in rows]

        dash_html = _build_facilities_html(tickets)
    except Exception as exc:
        erro = f"Erro ao carregar dados de Facilities: {exc}"

    return templates.TemplateResponse("indicadores/facilities.html", {
        "request": request,
        "dash_html": dash_html,
        "erro": erro,
    })


@router.get("/indicadores/treinamentos")
def treinamentos_dash(request: Request, departamento: str = "", mes: str = "", ano: str = "",
                      empresa: str = ""):
    erro = None
    dash_html = ""
    try:
        dash_html = _build_treinamentos_html(departamento, mes, ano, empresa)
    except Exception as exc:
        erro = f"Erro ao carregar dados de Treinamentos: {exc}"

    return templates.TemplateResponse("indicadores/treinamentos.html", {
        "request": request,
        "dash_html": dash_html,
        "erro": erro,
    })


@router.get("/indicadores/vagas")
def vagas_dash(request: Request, departamento: str = "", mes: str = "", ano: str = ""):
    erro = None
    dash_html = ""
    try:
        dash_html = _build_vagas_html(departamento, mes, ano)
    except Exception as exc:
        erro = f"Erro ao carregar dados de Vagas: {exc}"

    return templates.TemplateResponse("indicadores/vagas.html", {
        "request": request,
        "dash_html": dash_html,
        "erro": erro,
    })


def _folha_opcoes() -> tuple[list[str], list[str]]:
    """Retorna (todas_empresas, todas_competencias) para os dropdowns de folha."""
    emp_rows  = _db_rows("SELECT DISTINCT empresa_nome FROM folha_arquivos WHERE empresa_nome IS NOT NULL ORDER BY empresa_nome")
    comp_rows = _db_rows("SELECT DISTINCT competencia FROM folha_funcionarios WHERE competencia IS NOT NULL ORDER BY competencia DESC")
    return (
        [r["empresa_nome"] for r in emp_rows],
        [r["competencia"]  for r in comp_rows],
    )


@router.get("/indicadores/folha-visao-custo")
def folha_visao_custo(request: Request, empresa: str = "", competencia: str = ""):
    erro = None; dash_html = ""
    try:
        todas_empresas, todas_competencias = _folha_opcoes()
        dash_html = _build_folha_visao_custo_html(empresa, competencia, todas_empresas, todas_competencias)
    except Exception as exc:
        erro = f"Erro ao carregar dados de folha: {exc}"
    return templates.TemplateResponse("indicadores/folha_visao_custo.html", {
        "request": request, "dash_html": dash_html, "erro": erro,
    })


@router.get("/indicadores/folha-holerite")
def folha_holerite(request: Request, empresa: str = "", competencia: str = "", colaborador: str = ""):
    erro = None; dash_html = ""
    try:
        todas_empresas, todas_competencias = _folha_opcoes()
        # Lista de colaboradores disponíveis (com filtros de empresa/competência)
        where_c, params_c = _folha_query_filters(empresa, competencia)
        colab_rows = _db_rows(f"""
            SELECT DISTINCT ff.nome
            FROM folha_funcionarios ff
            JOIN folha_arquivos fa ON fa.id_arquivo = ff.id_arquivo
            {where_c}
            ORDER BY ff.nome
        """, params_c)
        todos_colaboradores = [r["nome"] for r in colab_rows]
        dash_html = _build_folha_holerite_html(
            empresa, competencia, colaborador,
            todas_empresas, todas_competencias, todos_colaboradores,
        )
    except Exception as exc:
        erro = f"Erro ao carregar dados de folha: {exc}"
    return templates.TemplateResponse("indicadores/folha_holerite.html", {
        "request": request, "dash_html": dash_html, "erro": erro,
    })


@router.get("/indicadores/folha-lista")
def folha_lista(request: Request, empresa: str = "", competencia: str = ""):
    erro = None; dash_html = ""
    try:
        todas_empresas, todas_competencias = _folha_opcoes()
        dash_html = _build_folha_lista_html(empresa, competencia, todas_empresas, todas_competencias)
    except Exception as exc:
        erro = f"Erro ao carregar dados de folha: {exc}"
    return templates.TemplateResponse("indicadores/folha_lista.html", {
        "request": request, "dash_html": dash_html, "erro": erro,
    })


@router.get("/indicadores/folha-custo-colaborador")
def folha_custo_colaborador(request: Request, empresa: str = "", competencia: str = ""):
    erro = None; dash_html = ""
    try:
        todas_empresas, todas_competencias = _folha_opcoes()
        dash_html = _build_folha_custo_colab_html(empresa, competencia, todas_empresas, todas_competencias)
    except Exception as exc:
        erro = f"Erro ao carregar dados de folha: {exc}"
    return templates.TemplateResponse("indicadores/folha_custo_colaborador.html", {
        "request": request, "dash_html": dash_html, "erro": erro,
    })


# ─── Banco de Horas ───────────────────────────────────────────────────────────

def _bh_time_to_minutes(t_str: str) -> int:
    if not t_str or str(t_str).strip() in ("None", "nan", "NaT", "", "00:00"):
        return 0
    s = str(t_str).strip()
    neg = -1 if s.startswith("-") else 1
    s = s.lstrip("-")
    try:
        h, m = s.split(":")
        return neg * (int(h) * 60 + int(m))
    except Exception:
        return 0


def _bh_minutes_to_time(minutes: int) -> str:
    if minutes == 0:
        return "00:00"
    sinal = "-" if minutes < 0 else ""
    m = abs(int(minutes))
    return f"{sinal}{m // 60:02d}:{m % 60:02d}"


def _fetch_ifractal_odata(entity: str) -> list[dict]:
    """Busca todas as linhas de uma entidade do OData ifractal."""
    token = os.getenv("CATWORLD_TOKEN", "")
    if not token:
        raise RuntimeError("CATWORLD_TOKEN não configurado.")
    base = "https://catworld.77indicadores.com.br/api/odata/porsche/ifractal"
    hdrs = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    url: str | None = f"{base}/{entity}"
    rows: list[dict] = []
    while url:
        resp = requests.get(url, headers=hdrs, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        rows.extend(data.get("value", []))
        url = data.get("@odata.nextLink") or data.get("@odata.nextlink")
    return rows


_RE_HMS = re.compile(r"\b(\d{1,2}:\d{2}:\d{2})\b")


def _norm_odata_time(s) -> str:
    """Extrai HH:MM:SS de strings OData (ISO ou JS Date); retorna '' se vazio."""
    s = str(s or "").strip()
    m = _RE_HMS.search(s)
    return m.group(1) if m else s


def _fetch_banco_horas() -> list[dict]:
    rows = _fetch_ifractal_odata("ifractal_extrato_banco_horas")
    result = []
    for r in rows:
        d = dict(r) if not isinstance(r, dict) else r
        nome = str(d.get("pessoa") or d.get("nome") or "").strip()
        if not nome:
            continue
        data_raw = d.get("data") or d.get("data_referencia") or ""
        try:
            data_dt = datetime.strptime(str(data_raw)[:10], "%Y-%m-%d").date()
        except Exception:
            try:
                data_dt = datetime.strptime(str(data_raw)[:10], "%d/%m/%Y").date()
            except Exception:
                data_dt = None
        result.append({
            "pessoa": nome,
            "data_dt": data_dt,
            "data_fmt": data_dt.strftime("%d/%m/%Y") if data_dt else "-",
            "credito": str(d.get("credito") or "---").strip(),
            "debito": str(d.get("debito") or "---").strip(),
            "saldo": str(d.get("saldo") or "00:00").strip(),
            "saldo_min": _bh_time_to_minutes(str(d.get("saldo") or "")),
            "empresa": str(d.get("empresa") or "").strip(),
            "departamento": str(d.get("departamento") or "").strip(),
            "cargo": str(d.get("cargo") or "").strip(),
            "periodo": str(d.get("banco_horas") or "").strip(),
        })
    return result


def _build_banco_horas_html(rows: list[dict], all_rows: list[dict] | None = None,
                            empresa_sel: str = "", departamento_sel: str = "",
                            mes_sel: str = "") -> str:
    all_rows = all_rows or rows
    empresas     = sorted({r["empresa"]     for r in all_rows if r["empresa"]})
    departamentos = sorted({r["departamento"] for r in all_rows if r["departamento"]})
    meses = sorted({r["data_dt"].strftime("%Y-%m") for r in all_rows if r.get("data_dt")},
                   reverse=True)

    # ── filtros ──────────────────────────────────────────────────────────────
    def _opt(val, sel, label=None):
        return f'<option value="{val}"{" selected" if val==sel else ""}>{label or val}</option>'
    opts_emp  = "".join(
        f'<option value="{e}"{" selected" if e == empresa_sel else ""}>{empresa_curta(e)}</option>'
        for e in empresas
    )
    opts_dep  = "".join(_opt(d, departamento_sel) for d in departamentos)
    opts_mes  = "".join(_opt(m, mes_sel, label=_rotulo_mes(m)) for m in meses)
    limpar    = ('<a href="/indicadores/banco-horas" class="bh-limpar">✕ Limpar</a>'
                 if (empresa_sel or departamento_sel or mes_sel) else "")
    filtros_html = f"""
<form method="get" action="/indicadores/banco-horas" class="bh-filtros" id="bhForm">
  <div class="bh-filtros-inner">
    <div class="bh-filtro-group">
      <label>Empresa</label>
      <select name="empresa" onchange="this.form.submit()">
        <option value="">Todas as empresas</option>{opts_emp}
      </select>
    </div>
    <div class="bh-filtro-group">
      <label>Departamento</label>
      <select name="departamento" onchange="this.form.submit()">
        <option value="">Todos os departamentos</option>{opts_dep}
      </select>
    </div>
    <div class="bh-filtro-group">
      <label>Mês</label>
      <select name="mes" onchange="this.form.submit()">
        <option value="">Todos os meses</option>{opts_mes}
      </select>
    </div>
    {limpar}
  </div>
</form>"""

    # Pega o registro mais recente por pessoa
    por_pessoa: dict[str, dict] = {}
    for r in rows:
        p = r["pessoa"]
        if p not in por_pessoa or (r["data_dt"] and (not por_pessoa[p]["data_dt"] or r["data_dt"] > por_pessoa[p]["data_dt"])):
            por_pessoa[p] = r

    # Ordena: negativos primeiro (mais negativo no topo), depois positivos decrescente
    pessoas = sorted(por_pessoa.values(), key=lambda x: x["saldo_min"])

    positivos = [p for p in pessoas if p["saldo_min"] > 0]
    negativos = [p for p in pessoas if p["saldo_min"] < 0]
    neutros   = [p for p in pessoas if p["saldo_min"] == 0]

    total_pos_min = sum(p["saldo_min"] for p in positivos)
    total_neg_min = sum(p["saldo_min"] for p in negativos)

    def row_html(r: dict) -> str:
        cor = "#e31837" if r["saldo_min"] < 0 else ("#28a745" if r["saldo_min"] > 0 else "#888")
        icone = "🔴" if r["saldo_min"] < 0 else ("🟢" if r["saldo_min"] > 0 else "⚪")
        sub = " · ".join(filter(None, [r.get("departamento"), r.get("empresa")]))
        return (
            f"<tr>"
            f"<td><div style='font-weight:600'>{icone} {r['pessoa']}</div>"
            f"<div style='font-size:.75rem;color:#888'>{sub}</div></td>"
            f"<td style='text-align:center;font-size:.8rem'>{r['data_fmt']}</td>"
            f"<td style='text-align:center'>{r['credito']}</td>"
            f"<td style='text-align:center'>{r['debito']}</td>"
            f"<td style='text-align:center;font-weight:bold;color:{cor}'>{r['saldo']}</td>"
            f"</tr>"
        )

    linhas_neg = "".join(row_html(r) for r in negativos) if negativos else "<tr><td colspan='5' style='text-align:center;color:#888'>Nenhum saldo negativo</td></tr>"
    linhas_pos = "".join(row_html(r) for r in sorted(positivos, key=lambda x: -x["saldo_min"])) if positivos else "<tr><td colspan='5' style='text-align:center;color:#888'>Nenhum saldo positivo</td></tr>"
    linhas_neu = "".join(row_html(r) for r in neutros) if neutros else ""

    data_ref = max((r["data_dt"] for r in por_pessoa.values() if r["data_dt"]), default=None)
    data_ref_fmt = data_ref.strftime("%d/%m/%Y") if data_ref else "-"
    periodo_label = next((r["periodo"] for r in por_pessoa.values() if r.get("periodo")), "")

    return filtros_html + f"""
<style>
.bh-kpis{{display:flex;gap:16px;flex-wrap:wrap;margin-bottom:24px}}
.bh-kpi{{background:#fff;border-radius:10px;padding:18px 24px;flex:1;min-width:160px;box-shadow:0 1px 4px rgba(0,0,0,.07);border-top:4px solid var(--cor)}}
.bh-kpi span{{display:block;font-size:.75rem;color:#666;margin-bottom:4px}}
.bh-kpi strong{{font-size:1.5rem;font-weight:700;color:var(--cor)}}
.bh-section{{background:#fff;border-radius:10px;box-shadow:0 1px 4px rgba(0,0,0,.07);margin-bottom:20px;overflow:hidden}}
.bh-section-head{{padding:12px 18px;font-weight:600;font-size:.85rem;display:flex;justify-content:space-between;align-items:center}}
.bh-section-head.neg{{background:#fff0f0;color:#c0392b;border-left:4px solid #e31837}}
.bh-section-head.pos{{background:#f0fff4;color:#1a7a3c;border-left:4px solid #28a745}}
.bh-section-head.neu{{background:#f8f8f8;color:#555;border-left:4px solid #aaa}}
.bh-table{{width:100%;border-collapse:collapse;font-size:.82rem}}
.bh-table th{{padding:9px 12px;background:#f5f5f5;text-align:left;font-weight:600;font-size:.75rem;text-transform:uppercase;color:#555;border-bottom:2px solid #e5e7eb}}
.bh-table td{{padding:9px 12px;border-bottom:1px solid #f0f0f0}}
.bh-table tr:last-child td{{border-bottom:none}}
.bh-ref{{font-size:.75rem;color:#888;margin-bottom:16px}}
.bh-filtros{{background:#fff;border-radius:10px;box-shadow:0 1px 4px rgba(0,0,0,.07);padding:16px 20px;margin-bottom:20px}}
.bh-filtros-inner{{display:flex;gap:16px;align-items:flex-end;flex-wrap:wrap}}
.bh-filtro-group{{display:flex;flex-direction:column;gap:4px;min-width:200px}}
.bh-filtro-group label{{font-size:.72rem;font-weight:600;color:#666;text-transform:uppercase;letter-spacing:.04em}}
.bh-filtro-group select{{padding:8px 12px;border:1px solid #d1d5db;border-radius:6px;font-size:.85rem;color:#111;background:#fafafa;cursor:pointer;outline:none}}
.bh-filtro-group select:focus{{border-color:#e31837;box-shadow:0 0 0 2px rgba(227,24,55,.12)}}
.bh-limpar{{font-size:.78rem;color:#e31837;text-decoration:none;padding:8px 4px;white-space:nowrap;align-self:flex-end}}
.bh-limpar:hover{{text-decoration:underline}}
</style>

<p class="bh-ref">Referência: última atualização em <strong>{data_ref_fmt}</strong> · {len(por_pessoa)} colaboradores{"  ·  Período: " + periodo_label if periodo_label else ""}</p>

<div class="bh-kpis">
  <div class="bh-kpi" style="--cor:#e31837">
    <span>Saldo negativo</span>
    <strong>{len(negativos)}</strong>
    <small style="color:#888">{_bh_minutes_to_time(total_neg_min)} acumulado</small>
  </div>
  <div class="bh-kpi" style="--cor:#28a745">
    <span>Saldo positivo</span>
    <strong>{len(positivos)}</strong>
    <small style="color:#888">{_bh_minutes_to_time(total_pos_min)} acumulado</small>
  </div>
  <div class="bh-kpi" style="--cor:#888">
    <span>Zerado / sem saldo</span>
    <strong>{len(neutros)}</strong>
    <small style="color:#888">&nbsp;</small>
  </div>
  <div class="bh-kpi" style="--cor:#555">
    <span>Total colaboradores</span>
    <strong>{len(por_pessoa)}</strong>
    <small style="color:#888">&nbsp;</small>
  </div>
</div>

<div class="bh-section">
  <div class="bh-section-head neg">
    <span>🔴 Saldo negativo ({len(negativos)})</span>
    <span>{_bh_minutes_to_time(total_neg_min)}</span>
  </div>
  <table class="bh-table">
    <thead><tr><th>Nome</th><th>Referência</th><th>Crédito</th><th>Débito</th><th>Saldo</th></tr></thead>
    <tbody>{linhas_neg}</tbody>
  </table>
</div>

<div class="bh-section">
  <div class="bh-section-head pos">
    <span>🟢 Saldo positivo ({len(positivos)})</span>
    <span>{_bh_minutes_to_time(total_pos_min)}</span>
  </div>
  <table class="bh-table">
    <thead><tr><th>Nome</th><th>Referência</th><th>Crédito</th><th>Débito</th><th>Saldo</th></tr></thead>
    <tbody>{linhas_pos}</tbody>
  </table>
</div>

{"<div class='bh-section'><div class='bh-section-head neu'><span>⚪ Zerado (" + str(len(neutros)) + ")</span></div><table class='bh-table'><thead><tr><th>Nome</th><th>Referência</th><th>Crédito</th><th>Débito</th><th>Saldo</th></tr></thead><tbody>" + linhas_neu + "</tbody></table></div>" if neutros else ""}
"""


# ─── Horas Extras ──────────────────────────────────────────────────────────────

def _he_parse_minutes(t_str: str) -> int:
    """Converte HH:MM ou HH:MM:SS para minutos; ignora nulos."""
    s = str(t_str or "").strip()
    if not s or s.lower() in ("none", "nan", "", "null"):
        return 0
    parts = s.split(":")
    try:
        h = int(parts[0])
        m = int(parts[1]) if len(parts) > 1 else 0
        return h * 60 + m
    except Exception:
        return 0


def _he_faixa(minutos: int) -> str:
    if minutos <= 0:
        return ""
    if minutos <= 15:
        return "Até 15 min"
    if minutos <= 120:
        return "16 min – 2h"
    return "Acima de 2h"


def _fetch_hora_extra() -> list[dict]:
    rows = _fetch_ifractal_odata("ifractal_hora_extra")
    result = []
    for r in rows:
        d = dict(r) if not isinstance(r, dict) else r
        nome = str(d.get("pessoa") or "").strip()
        credito_str = _norm_odata_time(d.get("bh_credito") or "")
        credito_min = _he_parse_minutes(credito_str)
        if not nome or credito_min <= 0:
            continue
        data_raw = d.get("data") or d.get("dt") or ""
        try:
            data_dt = datetime.strptime(str(data_raw)[:10], "%Y-%m-%d").date()
        except Exception:
            data_dt = None
        result.append({
            "pessoa":       nome,
            "empresa":      str(d.get("empresa") or "").strip(),
            "departamento": str(d.get("departamento") or "").strip(),
            "cargo":        str(d.get("cargo") or "").strip(),
            "data_dt":      data_dt,
            "mes":          data_dt.strftime("%Y-%m") if data_dt else "0000-00",
            "mes_fmt":      data_dt.strftime("%b/%Y") if data_dt else "-",
            "credito_min":  credito_min,
            "credito_fmt":  f"{credito_min // 60:02d}:{credito_min % 60:02d}",
            "faixa":        _he_faixa(credito_min),
        })
    return result


def _build_hora_extra_html(rows: list[dict], all_rows: list[dict] | None = None,  # noqa: C901
                           empresa_sel: str = "", cargo_sel: str = "",
                           ano_sel: str = "", mes_sel: str = "",
                           departamento_sel: str = "") -> str:
    all_rows = all_rows or rows
    empresas = sorted({r["empresa"] for r in all_rows if r["empresa"]})
    cargos   = sorted({r["cargo"]   for r in all_rows if r["cargo"]})
    departamentos = sorted({r["departamento"] for r in all_rows if r.get("departamento")})
    anos     = sorted({str(r["data_dt"].year) for r in all_rows if r.get("data_dt")}, reverse=True)
    meses_disp = sorted({r["mes"] for r in all_rows if r.get("mes")})

    _MES_NOMES = {"01":"Jan","02":"Fev","03":"Mar","04":"Abr","05":"Mai","06":"Jun",
                  "07":"Jul","08":"Ago","09":"Set","10":"Out","11":"Nov","12":"Dez"}

    def _opt(val, sel, label=None):
        return f'<option value="{val}"{" selected" if val == sel else ""}>{label or val}</option>'

    opts_emp   = "".join(_opt(e, empresa_sel, label=empresa_curta(e)) for e in empresas)
    opts_cargo = "".join(_opt(c, cargo_sel)   for c in cargos)
    opts_dep   = "".join(_opt(d, departamento_sel) for d in departamentos)
    opts_ano   = "".join(_opt(a, ano_sel) for a in anos)
    opts_mes   = "".join(
        _opt(m, mes_sel, label=f"{_MES_NOMES.get(m[5:7], m[5:7])} {m[:4]}")
        for m in meses_disp
    )
    has_filter = any([empresa_sel, cargo_sel, ano_sel, mes_sel, departamento_sel])
    limpar = (f'<a href="/indicadores/horas-extras" class="he-limpar">✕ Limpar</a>'
              if has_filter else "")

    FAIXAS = ["Até 15 min", "16 min – 2h", "Acima de 2h"]
    # stacked bar colors: gray / red / dark
    CF = {"Até 15 min": "#9ca3af", "16 min – 2h": "#e31837", "Acima de 2h": "#374151"}

    from collections import defaultdict  # noqa: PLC0415

    def _agg(lst):
        return len(lst), sum(r["credito_min"] for r in lst)

    por_faixa:   dict[str, list] = defaultdict(list)
    por_empresa: dict[str, list] = defaultdict(list)
    por_depto:   dict[str, list] = defaultdict(list)
    por_cargo_d: dict[str, list] = defaultdict(list)
    por_mes: dict[str, list] = defaultdict(list)

    for r in rows:
        f = r["faixa"]
        if not f:
            continue
        por_faixa[f].append(r)
        por_empresa[r["empresa"]].append(r)
        por_depto[r["departamento"]].append(r)
        por_cargo_d[r["cargo"]].append(r)
        por_mes[r["mes"]].append(r)

    total_oc  = sum(len(v) for v in por_faixa.values())
    total_min = sum(r["credito_min"] for r in rows if r["faixa"])
    total_col = len(set(r["pessoa"] for r in rows))
    a2h_oc, a2h_min = _agg(por_faixa.get("Acima de 2h", []))
    pct_a2h   = round(a2h_oc / total_oc * 100) if total_oc else 0
    med_min   = total_min // total_oc if total_oc else 0
    med_fmt   = f"{med_min//60}h{med_min%60:02d}" if med_min >= 60 else f"{med_min}min"
    med_col   = total_min // total_col if total_col else 0
    med_col_f = f"{med_col//60}h{med_col%60:02d}" if med_col >= 60 else f"{med_col}min"
    tot_h_fmt = f"{total_min//60:02d}:{total_min%60:02d}"
    a2h_h_fmt = f"{a2h_min//60:02d}:{a2h_min%60:02d}"

    meses_sorted = sorted(por_mes.keys())

    total_oc_fmt = f"{total_oc:,}".replace(",", ".")
    year_ref     = max((r["data_dt"].year for r in rows if r.get("data_dt")), default=2026)

    # ── SVG helpers ────────────────────────────────────────────────────────────

    def _svg_stacked():
        if not meses_sorted:
            return "<p style='color:#888;text-align:center;padding:20px'>Sem dados</p>"
        PL, PR, PT, PB = 8, 8, 28, 28
        CW, CH = 400, 200
        iw, ih = CW - PL - PR, CH - PT - PB
        n       = len(meses_sorted)
        totals  = [len(por_mes[m]) for m in meses_sorted]
        max_t   = max(totals) if totals else 1
        bar_w   = max(18, min(44, iw // n - 8))
        slot_w  = iw / n
        p = [f'<svg viewBox="0 0 {CW} {CH}" xmlns="http://www.w3.org/2000/svg"'
             f' style="width:100%;max-height:200px;display:block">']
        for i, mes in enumerate(meses_sorted):
            rows_m  = por_mes[mes]
            total_m = len(rows_m)
            cx      = PL + slot_w * i + slot_w / 2
            bx      = cx - bar_w / 2
            y_cur   = PT + ih
            for f in FAIXAS:
                cnt = len([r for r in rows_m if r["faixa"] == f])
                if not cnt:
                    continue
                seg_h = max(1, int(cnt / max_t * ih))
                seg_y = y_cur - seg_h
                p.append(f'<rect x="{bx:.1f}" y="{seg_y:.1f}" width="{bar_w}"'
                         f' height="{seg_h:.1f}" fill="{CF[f]}"/>')
                if seg_h > 14:
                    mid_y = seg_y + seg_h / 2 + 4
                    p.append(f'<text x="{cx:.1f}" y="{mid_y:.1f}" text-anchor="middle"'
                             f' font-size="9" fill="#fff" font-weight="700"'
                             f' font-family="Inter,sans-serif">{cnt}</text>')
                y_cur -= seg_h
            p.append(f'<text x="{cx:.1f}" y="{y_cur-4:.1f}" text-anchor="middle"'
                     f' font-size="10" fill="#333" font-weight="700"'
                     f' font-family="Inter,sans-serif">{total_m}</text>')
            lbl = rows_m[0]["mes_fmt"] if rows_m else mes
            p.append(f'<text x="{cx:.1f}" y="{CH-2}" text-anchor="middle"'
                     f' font-size="10" fill="#666" font-family="Inter,sans-serif">{lbl}</text>')
        p.append('</svg>')
        return "".join(p)

    def _svg_line():
        if not meses_sorted:
            return "<p style='color:#888;text-align:center;padding:20px'>Sem dados</p>"
        PL, PR, PT, PB = 8, 8, 24, 28
        CW, CH  = 400, 200
        iw, ih  = CW - PL - PR, CH - PT - PB
        n       = len(meses_sorted)
        hrs     = [sum(r["credito_min"] for r in por_mes[m]) for m in meses_sorted]
        max_h   = max(hrs) if hrs else 1
        slot_w  = iw / n
        pts     = [(PL + slot_w * i + slot_w / 2,
                    PT + ih - int(v / max_h * ih)) for i, v in enumerate(hrs)]
        lp      = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        area    = (f"{pts[0][0]:.1f},{PT+ih} " + lp +
                   f" {pts[-1][0]:.1f},{PT+ih}")
        p = [f'<svg viewBox="0 0 {CW} {CH}" xmlns="http://www.w3.org/2000/svg"'
             f' style="width:100%;max-height:200px;display:block">']
        p.append(f'<polygon points="{area}" fill="rgba(227,24,55,.07)"/>')
        p.append(f'<polyline points="{lp}" fill="none" stroke="#e31837"'
                 f' stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>')
        for i, (x, y) in enumerate(pts):
            hm  = hrs[i]
            hl  = f"{hm//60}:{hm%60:02d}"
            lbl = por_mes[meses_sorted[i]][0]["mes_fmt"]
            p.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="#fff"'
                     f' stroke="#e31837" stroke-width="2.5"/>')
            p.append(f'<text x="{x:.1f}" y="{y-9:.1f}" text-anchor="middle"'
                     f' font-size="9" fill="#333" font-weight="700"'
                     f' font-family="Inter,sans-serif">{hl}</text>')
            p.append(f'<text x="{x:.1f}" y="{CH-2}" text-anchor="middle"'
                     f' font-size="10" fill="#666" font-family="Inter,sans-serif">{lbl}</text>')
        p.append('</svg>')
        return "".join(p)

    def _svg_hbars(agrupado: dict, top: int = 8, color: str = "#e31837") -> str:
        itens = sorted([(k, len(v)) for k, v in agrupado.items() if k],
                       key=lambda x: -x[1])[:top]
        if not itens:
            return "<p style='color:#888;padding:16px'>Sem dados</p>"
        max_v  = itens[0][1]
        BAR_H  = 22
        GAP    = 10
        LBL_W  = 86
        VAL_W  = 38
        CW     = 380
        PT     = 6
        n      = len(itens)
        CH     = n * (BAR_H + GAP) + PT
        ba     = CW - LBL_W - VAL_W
        p = [f'<svg viewBox="0 0 {CW} {CH}" xmlns="http://www.w3.org/2000/svg"'
             f' style="width:100%;display:block">']
        for i, (label, val) in enumerate(itens):
            y  = PT + i * (BAR_H + GAP)
            bw = int(val / max_v * ba) if max_v else 0
            disp  = label.title()
            short = (disp[:13] + "…") if len(disp) > 14 else disp
            p.append(f'<rect x="{LBL_W}" y="{y}" width="{ba}" height="{BAR_H}"'
                     f' fill="#f5f5f5" rx="3"/>')
            if bw > 0:
                p.append(f'<rect x="{LBL_W}" y="{y}" width="{bw}" height="{BAR_H}"'
                         f' fill="{color}" rx="3"/>')
            my = y + BAR_H / 2 + 4
            p.append(f'<text x="{LBL_W-5}" y="{my:.1f}" text-anchor="end" font-size="11"'
                     f' fill="#444" font-family="Inter,sans-serif">{short}</text>')
            p.append(f'<text x="{LBL_W+ba+4}" y="{my:.1f}" text-anchor="start"'
                     f' font-size="11" fill="#333" font-weight="700"'
                     f' font-family="Inter,sans-serif">{val}</text>')
        p.append('</svg>')
        return "".join(p)

    def _svg_donut_empresa() -> str:
        import math as _math  # noqa: PLC0415
        itens = sorted([(k, len(v)) for k, v in por_empresa.items() if k],
                       key=lambda x: -x[1])[:6]
        if not itens:
            return "<p style='color:#888;padding:16px'>Sem dados</p>"
        total = sum(v for _, v in itens)
        COLORS = ["#e31837", "#374151", "#9ca3af", "#60a5fa", "#7f1d1d", "#f59e0b"]
        CW, CH = 380, 210
        cx, cy = 105, 100
        R, ri  = 82, 46
        p = [f'<svg viewBox="0 0 {CW} {CH}" xmlns="http://www.w3.org/2000/svg"'
             f' style="width:100%;display:block">']
        start = -_math.pi / 2
        for i, (label, val) in enumerate(itens):
            frac  = val / total
            sweep = 2 * _math.pi * frac
            end   = start + sweep
            large = 1 if sweep > _math.pi else 0
            x1  = cx + R  * _math.cos(start);  y1  = cy + R  * _math.sin(start)
            x2  = cx + R  * _math.cos(end);    y2  = cy + R  * _math.sin(end)
            xi1 = cx + ri * _math.cos(end);    yi1 = cy + ri * _math.sin(end)
            xi2 = cx + ri * _math.cos(start);  yi2 = cy + ri * _math.sin(start)
            col = COLORS[i % len(COLORS)]
            if frac > 0.9999:
                p.append(f'<circle cx="{cx}" cy="{cy}" r="{R}" fill="{col}"/>')
                p.append(f'<circle cx="{cx}" cy="{cy}" r="{ri}" fill="#fff"/>')
            else:
                d = (f"M {x1:.2f},{y1:.2f} A {R},{R} 0 {large},1 {x2:.2f},{y2:.2f}"
                     f" L {xi1:.2f},{yi1:.2f} A {ri},{ri} 0 {large},0 {xi2:.2f},{yi2:.2f} Z")
                p.append(f'<path d="{d}" fill="{col}"/>')
            start = end
        p.append(f'<text x="{cx}" y="{cy-8}" text-anchor="middle" font-size="20"'
                 f' font-weight="900" fill="#111" font-family="Inter,sans-serif">{total}</text>')
        p.append(f'<text x="{cx}" y="{cy+10}" text-anchor="middle" font-size="9"'
                 f' fill="#888" font-family="Inter,sans-serif">ocorrências</text>')
        lx = cx + R + 18
        for i, (label, val) in enumerate(itens):
            pct = round(val / total * 100)
            col = COLORS[i % len(COLORS)]
            ly  = 26 + i * 26
            disp = label.title()
            short = (disp[:18] + "…") if len(disp) > 19 else disp
            p.append(f'<rect x="{lx}" y="{ly-11}" width="11" height="11"'
                     f' fill="{col}" rx="2"/>')
            p.append(f'<text x="{lx+15}" y="{ly-2}" font-size="11" fill="#333"'
                     f' font-weight="700" font-family="Inter,sans-serif">{val}</text>')
            p.append(f'<text x="{lx+15}" y="{ly+10}" font-size="10" fill="#888"'
                     f' font-family="Inter,sans-serif">{short} · {pct}%</text>')
        p.append('</svg>')
        return "".join(p)

    def _svg_faixa_count() -> str:
        max_oc_f = max((len(por_faixa.get(f, [])) for f in FAIXAS), default=1)
        BAR_H, GAP, LBL_W, PCT_W = 28, 16, 90, 38
        CW = 380
        PT = 8
        CH = len(FAIXAS) * (BAR_H + GAP) + PT
        ba = CW - LBL_W - PCT_W
        p = [f'<svg viewBox="0 0 {CW} {CH}" xmlns="http://www.w3.org/2000/svg"'
             f' style="width:100%;display:block">']
        for i, f in enumerate(FAIXAS):
            oc, _ = _agg(por_faixa.get(f, []))
            pct   = round(oc / total_oc * 100) if total_oc else 0
            y     = PT + i * (BAR_H + GAP)
            bw    = int(oc / max_oc_f * ba) if max_oc_f else 0
            my    = y + BAR_H / 2 + 4
            p.append(f'<rect x="{LBL_W}" y="{y}" width="{ba}" height="{BAR_H}"'
                     f' fill="#f5f5f5" rx="3"/>')
            if bw > 0:
                p.append(f'<rect x="{LBL_W}" y="{y}" width="{bw}" height="{BAR_H}"'
                         f' fill="{CF[f]}" rx="3"/>')
            if bw > 40:
                p.append(f'<text x="{LBL_W+bw-6}" y="{my:.1f}" text-anchor="end"'
                         f' font-size="11" fill="#fff" font-weight="700"'
                         f' font-family="Inter,sans-serif">{oc}</text>')
            p.append(f'<text x="{LBL_W-5}" y="{my:.1f}" text-anchor="end"'
                     f' font-size="11" fill="#444" font-family="Inter,sans-serif">{f}</text>')
            p.append(f'<text x="{CW-2}" y="{my:.1f}" text-anchor="end"'
                     f' font-size="11" fill="#666" font-family="Inter,sans-serif">{pct}%</text>')
        p.append('</svg>')
        return "".join(p)

    def _svg_faixa_hours() -> str:
        fh  = [(f, _agg(por_faixa.get(f, []))[1]) for f in FAIXAS]
        max_m = max(v for _, v in fh) if fh else 1
        BAR_H, GAP, LBL_W, PCT_W = 28, 16, 90, 38
        CW = 380
        PT = 8
        CH = len(FAIXAS) * (BAR_H + GAP) + PT
        ba = CW - LBL_W - PCT_W
        p = [f'<svg viewBox="0 0 {CW} {CH}" xmlns="http://www.w3.org/2000/svg"'
             f' style="width:100%;display:block">']
        for i, (f, mins) in enumerate(fh):
            pct  = round(mins / total_min * 100) if total_min else 0
            y    = PT + i * (BAR_H + GAP)
            bw   = int(mins / max_m * ba) if max_m else 0
            hl   = f"{mins//60}:{mins%60:02d}"
            my   = y + BAR_H / 2 + 4
            p.append(f'<rect x="{LBL_W}" y="{y}" width="{ba}" height="{BAR_H}"'
                     f' fill="#f5f5f5" rx="3"/>')
            if bw > 0:
                p.append(f'<rect x="{LBL_W}" y="{y}" width="{bw}" height="{BAR_H}"'
                         f' fill="{CF[f]}" rx="3"/>')
            if bw > 55:
                p.append(f'<text x="{LBL_W+bw-6}" y="{my:.1f}" text-anchor="end"'
                         f' font-size="11" fill="#fff" font-weight="700"'
                         f' font-family="Inter,sans-serif">{hl}</text>')
            p.append(f'<text x="{LBL_W-5}" y="{my:.1f}" text-anchor="end"'
                     f' font-size="11" fill="#444" font-family="Inter,sans-serif">{f}</text>')
            p.append(f'<text x="{CW-2}" y="{my:.1f}" text-anchor="end"'
                     f' font-size="11" fill="#666" font-family="Inter,sans-serif">{pct}%</text>')
        p.append('</svg>')
        return "".join(p)

    # ── generate all SVGs ──────────────────────────────────────────────────────
    svg_stacked   = _svg_stacked()
    svg_line      = _svg_line()
    svg_emp       = _svg_donut_empresa()
    svg_dep       = _svg_hbars(por_depto,   top=8)
    svg_f_cnt     = _svg_faixa_count()
    svg_f_hrs     = _svg_faixa_hours()

    # ── hero faixa cards ────────────────────────────────────────────────────────
    hero_top = ""
    for f in FAIXAS:
        oc, mins = _agg(por_faixa.get(f, []))
        pct      = round(oc / total_oc * 100) if total_oc else 0
        h_fmt    = f"{mins//60:02d}:{mins%60:02d}"
        hero_top += (
            f'<div class="he-hkpi">'
            f'<div class="he-hkpi-lbl">{f}</div>'
            f'<div class="he-hkpi-val">{oc}</div>'
            f'<div class="he-hkpi-sub">{h_fmt}</div>'
            f'<div class="he-hkpi-pct">{pct}% das ocorrências</div>'
            f'</div>'
        )
    hero_bot = ""
    for f in FAIXAS:
        oc, _ = _agg(por_faixa.get(f, []))
        pct   = round(oc / total_oc * 100) if total_oc else 0
        hero_bot += (
            f'<div class="he-hkpi he-hkpi-pct">'
            f'<div class="he-hkpi-lbl">% {f}</div>'
            f'<div class="he-hkpi-val">{pct}%</div>'
            f'<div class="he-hkpi-pct">das ocorrências</div>'
            f'</div>'
        )

    # ── legend strings ─────────────────────────────────────────────────────────
    def _dot(c, lbl):
        return (f'<span style="display:inline-flex;align-items:center;gap:4px;'
                f'font-size:11px;color:#555">'
                f'<span style="width:9px;height:9px;border-radius:50%;'
                f'background:{c};display:inline-block"></span>{lbl}</span>')
    leg_faixas = " ".join(_dot(CF[f], f) for f in FAIXAS)
    leg_horas  = _dot("#e31837", "Horas (hh:mm)")
    leg_oc_pct = _dot("#e31837", "Ocorrências") + " " + _dot("#9ca3af", "% do total")

    css = """<style>
.he-filtros{background:#fff;border-radius:10px;box-shadow:0 1px 4px rgba(0,0,0,.07);padding:14px 20px;margin-bottom:16px}
.he-filtros-inner{display:flex;gap:14px;align-items:flex-end;flex-wrap:wrap}
.he-filtro-group{display:flex;flex-direction:column;gap:3px;min-width:190px}
.he-filtro-group label{font-size:.72rem;font-weight:600;color:#666;text-transform:uppercase;letter-spacing:.04em}
.he-filtro-group select{padding:8px 10px;border:1px solid #d1d5db;border-radius:6px;font-size:.84rem;color:#111;background:#fafafa;cursor:pointer;outline:none}
.he-filtro-group select:focus{border-color:#e31837;box-shadow:0 0 0 2px rgba(227,24,55,.10)}
.he-limpar{font-size:.78rem;color:#e31837;text-decoration:none;padding:8px 4px;white-space:nowrap;align-self:flex-end}
.he-limpar:hover{text-decoration:underline}
/* hero */
.he-hero{background:linear-gradient(135deg,#0f0f0f 0%,#1a0003 55%,#2a0007 100%);border-radius:12px;padding:20px 24px;margin-bottom:16px;display:grid;grid-template-columns:1fr 1.5fr;gap:20px;position:relative;overflow:hidden}
.he-hero::after{content:"";position:absolute;right:-40px;top:-60px;width:260px;height:260px;border-radius:50%;background:radial-gradient(circle,rgba(227,24,55,.3) 0%,transparent 70%);pointer-events:none}
.he-hero-badge{display:inline-block;background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.15);color:#ccc;font-size:.72rem;padding:4px 10px;border-radius:20px;margin-bottom:12px}
.he-hero-title{color:#fff;font-size:1.1rem;font-weight:700;margin-bottom:4px}
.he-hero-sub{color:#888;font-size:.8rem;margin-bottom:16px}
.he-hero-nums{display:flex;gap:24px;flex-wrap:wrap}
.he-hero-num{display:flex;flex-direction:column}
.he-hero-big{color:#fff;font-size:clamp(1.8rem,3vw,2.6rem);font-weight:900;letter-spacing:-.04em;line-height:1}
.he-hero-lbl{color:#888;font-size:.72rem;margin-top:3px}
.he-hero-kpis-wrap{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;align-content:start}
.he-hkpi{background:rgba(255,255,255,.055);border:1px solid rgba(255,255,255,.09);border-radius:8px;padding:10px 12px;border-left:3px solid #e31837}
.he-hkpi.he-hkpi-pct{border-left-color:rgba(227,24,55,.5)}
.he-hkpi-lbl{color:#aaa;font-size:.65rem;font-weight:600;text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px}
.he-hkpi-val{color:#fff;font-size:1.25rem;font-weight:900;letter-spacing:-.03em;line-height:1}
.he-hkpi-sub{color:#e31837;font-size:.72rem;font-weight:700;margin-top:2px}
.he-hkpi-pct{color:#777;font-size:.68rem;margin-top:2px}
/* panels */
.he-panel{background:#fff;border-radius:10px;box-shadow:0 1px 4px rgba(0,0,0,.07);overflow:hidden}
.he-panel-head{padding:11px 16px;font-weight:700;font-size:.84rem;background:#fafafa;border-left:4px solid #e31837;display:flex;justify-content:space-between;align-items:center}
.he-panel-head-right{font-size:.72rem;color:#888;font-weight:400;display:flex;gap:10px;flex-wrap:wrap}
.he-panel-body{padding:12px 14px}
/* grids */
.he-row-mid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:12px}
.he-row-bot{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:8px}
@media(max-width:1100px){
.he-hero{grid-template-columns:1fr}
.he-row-mid,.he-row-bot{grid-template-columns:1fr}
}
</style>"""

    return css + f"""
<form method="get" action="/indicadores/horas-extras" class="he-filtros">
  <div class="he-filtros-inner">
    <div class="he-filtro-group">
      <label>Empresa</label>
      <select name="empresa" onchange="this.form.submit()">
        <option value="">Todas as empresas</option>{opts_emp}
      </select>
    </div>
    <div class="he-filtro-group">
      <label>Setor</label>
      <select name="departamento" onchange="this.form.submit()">
        <option value="">Todos os setores</option>{opts_dep}
      </select>
    </div>
    <div class="he-filtro-group">
      <label>Cargo</label>
      <select name="cargo" onchange="this.form.submit()">
        <option value="">Todos os cargos</option>{opts_cargo}
      </select>
    </div>
    <div class="he-filtro-group">
      <label>Ano</label>
      <select name="ano" onchange="this.form.submit()">
        <option value="">Todos os anos</option>{opts_ano}
      </select>
    </div>
    <div class="he-filtro-group">
      <label>Mês</label>
      <select name="mes" onchange="this.form.submit()">
        <option value="">Todos os meses</option>{opts_mes}
      </select>
    </div>
    {limpar}
  </div>
</form>

<div class="he-hero">
  <div>
    <div class="he-hero-badge">Acumulado · {year_ref}</div>
    <div class="he-hero-title">Resumo de Horas Extras</div>
    <div class="he-hero-sub">Visão do período com foco em jornada extraordinária</div>
    <div class="he-hero-nums">
      <div class="he-hero-num">
        <div class="he-hero-big">{total_oc_fmt}</div>
        <div class="he-hero-lbl">ocorrências acumuladas no período</div>
      </div>
      <div class="he-hero-num">
        <div class="he-hero-big">{tot_h_fmt}</div>
        <div class="he-hero-lbl">total em horas</div>
      </div>
      <div class="he-hero-num">
        <div class="he-hero-big">{total_col}</div>
        <div class="he-hero-lbl">colaboradores com HE</div>
      </div>
    </div>
  </div>
  <div class="he-hero-kpis-wrap">
    {hero_top}{hero_bot}
  </div>
</div>

<div class="he-row-mid">
  <div class="he-panel">
    <div class="he-panel-head">Ocorrências por mês</div>
    <div class="he-panel-body">{svg_stacked}</div>
  </div>

  <div class="he-panel">
    <div class="he-panel-head">
      Horas extras por mês
      <div class="he-panel-head-right">{leg_horas}</div>
    </div>
    <div class="he-panel-body">{svg_line}</div>
  </div>

  <div class="he-panel">
    <div class="he-panel-head">
      Distribuição por faixa
      <div class="he-panel-head-right">{leg_oc_pct}</div>
    </div>
    <div class="he-panel-body">{svg_f_cnt}</div>
  </div>
</div>

<div class="he-row-bot">
  <div class="he-panel">
    <div class="he-panel-head">🏢 Por Empresa</div>
    <div class="he-panel-body">{svg_emp}</div>
  </div>

  <div class="he-panel">
    <div class="he-panel-head">🗂️ Por Departamento</div>
    <div class="he-panel-body">{svg_dep}</div>
  </div>

  <div class="he-panel">
    <div class="he-panel-head">
      Distribuição de horas por faixa
      <div class="he-panel-head-right">{_dot("#e31837","Horas (hh:mm)")} {_dot("#9ca3af","% do total")}</div>
    </div>
    <div class="he-panel-body">{svg_f_hrs}</div>
  </div>

</div>"""


@router.get("/indicadores/horas-extras")
def horas_extras(request: Request, empresa: str = "", cargo: str = "",
                 ano: str = "", mes: str = "", departamento: str = ""):
    erro = None
    dash_html = ""
    try:
        all_rows = _fetch_hora_extra()
        filtered = all_rows
        if empresa:
            filtered = [r for r in filtered if r["empresa"] == empresa]
        if departamento:
            filtered = [r for r in filtered if r.get("departamento") == departamento]
        if cargo:
            filtered = [r for r in filtered if r["cargo"] == cargo]
        if ano:
            filtered = [r for r in filtered if r.get("data_dt") and str(r["data_dt"].year) == ano]
        if mes:
            filtered = [r for r in filtered if r.get("mes") == mes]
        dash_html = _build_hora_extra_html(filtered, all_rows=all_rows,
                                           empresa_sel=empresa, cargo_sel=cargo,
                                           ano_sel=ano, mes_sel=mes,
                                           departamento_sel=departamento)
    except Exception as exc:
        import traceback; traceback.print_exc()
        erro = f"Erro ao buscar dados de horas extras: {exc}"
    return templates.TemplateResponse("indicadores/horas_extras.html", {
        "request": request,
        "dash_html": dash_html,
        "erro": erro,
    })


@router.get("/indicadores/banco-horas")
def banco_horas(request: Request, empresa: str = "", departamento: str = "", mes: str = ""):
    erro = None
    dash_html = ""
    try:
        all_rows = _fetch_banco_horas()
        filtered = all_rows
        if empresa:
            filtered = [r for r in filtered if r["empresa"] == empresa]
        if departamento:
            filtered = [r for r in filtered if r["departamento"] == departamento]
        if mes:
            filtered = [r for r in filtered
                        if r.get("data_dt") and r["data_dt"].strftime("%Y-%m") == mes]
        dash_html = _build_banco_horas_html(filtered, all_rows=all_rows,
                                            empresa_sel=empresa, departamento_sel=departamento,
                                            mes_sel=mes)
    except Exception as exc:
        erro = f"Erro ao buscar dados de banco de horas: {exc}"
    return templates.TemplateResponse("indicadores/banco_horas.html", {
        "request": request,
        "dash_html": dash_html,
        "erro": erro,
    })


# ─── Afastamentos ─────────────────────────────────────────────────────────────

_MESES_PT_AFAS = [
    "Janeiro","Fevereiro","Março","Abril","Maio","Junho",
    "Julho","Agosto","Setembro","Outubro","Novembro","Dezembro",
]


def _parse_dt_afas(s) -> "datetime | None":
    s = str(s or "").strip().split(" ")[0]
    if not s:
        return None
    try:
        if len(s) == 10 and s[2] == "/":
            return datetime(int(s[6:]), int(s[3:5]), int(s[0:2]))
        if len(s) == 10 and s[4] == "-":
            return datetime(int(s[0:4]), int(s[5:7]), int(s[8:10]))
    except Exception:
        pass
    return None


def _build_afastamentos_html(  # noqa: C901
    rows: list[dict],
    all_rows: list[dict] | None = None,
    empresa_sel: str = "",
    dep_sel: str = "",
    tipo_sel: str = "",
    ano_sel: str = "",
) -> str:
    import json as _json  # noqa: PLC0415

    def _to_iso(s: str) -> str:
        s = str(s or "").strip().split(" ")[0]
        if len(s) == 10 and s[2] == "/":
            return f"{s[6:]}-{s[3:5]}-{s[0:2]}"
        if len(s) == 10 and s[4] == "-":
            return s
        return ""

    records_js = _json.dumps([{
        "id":         str(r.get("matricula", "")),
        "name":       r.get("nome_colaborador", ""),
        "company":    empresa_curta(r.get("empresa", "")),
        "department": r.get("departamento", ""),
        "role":       r.get("cargo", ""),
        "type":       r.get("tipo_atestado", ""),
        "date":       _to_iso(str(r.get("data_atestado", ""))),
        "start":      _to_iso(str(r.get("data_inicio_afastamento", ""))),
        "end":        _to_iso(str(r.get("data_fim_afastamento", ""))),
        "days":       r.get("dias") or 0,
        "cid":        r.get("cid", ""),
    } for r in rows], ensure_ascii=False)

    css = """<style>
.af2{--red:#d5001c;--red2:#a90017;--line:#e4e6e9;--green:#15966a;
  --amber:#d58a13;--orange:#ef6b2e;--purple:#7157c8;--muted:#70747c;
  --shadow:0 12px 34px rgba(12,16,24,.08);--radius:18px;
  font-family:Inter,ui-sans-serif,system-ui,sans-serif;color:#16181c}
.af2 button,.af2 select,.af2 input{font:inherit}
.af2 button{cursor:pointer}
/* hero */
.af2 .af2-hero{display:flex;align-items:flex-end;justify-content:space-between;
  gap:18px;margin-bottom:20px;flex-wrap:wrap}
.af2 .af2-hero h2{margin:0;font-size:26px;letter-spacing:-.03em;font-weight:900}
.af2 .af2-hero p{margin:6px 0 0;color:var(--muted);font-size:13px}
.af2 .af2-updated{display:flex;align-items:center;gap:8px;color:#565b64;
  font-size:12px;background:#fff;border:1px solid var(--line);
  border-radius:999px;padding:8px 14px;white-space:nowrap}
.af2 .af2-updated i{width:8px;height:8px;border-radius:50%;background:var(--green);
  box-shadow:0 0 0 4px rgba(21,150,106,.14)}
/* filters */
.af2 .af2-filters{display:grid;grid-template-columns:repeat(5,minmax(130px,1fr)) auto;
  gap:12px;padding:16px;margin-bottom:18px;background:#fff;
  border:1px solid var(--line);border-radius:var(--radius);box-shadow:var(--shadow)}
.af2 .af2-field label{display:block;color:#777c84;font-size:10px;font-weight:850;
  letter-spacing:.08em;text-transform:uppercase;margin:0 0 7px 2px}
.af2 .af2-sw{position:relative}
.af2 .af2-field select{width:100%;height:42px;padding:0 36px 0 12px;
  border:1px solid var(--line);border-radius:11px;color:#2a2e34;
  background:#fafafa;outline:none;appearance:none}
.af2 .af2-field select:focus{background:#fff;border-color:#aeb2b9;
  box-shadow:0 0 0 3px rgba(0,0,0,.04)}
.af2 .af2-sw::after{content:"⌄";position:absolute;right:12px;top:50%;
  transform:translateY(-58%);color:#7f838a;pointer-events:none}
.af2 .af2-reset{align-self:end;height:42px;padding:0 16px;border-radius:11px;
  border:1px solid #e2b5bb;background:#fff5f6;color:var(--red2);
  font-weight:800;font-size:12px}
/* kpis */
.af2 .af2-kpis{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));
  gap:14px;margin-bottom:18px}
.af2 .af2-kpi{position:relative;overflow:hidden;min-height:120px;
  padding:17px 17px 14px;background:#fff;border:1px solid var(--line);
  border-radius:var(--radius);box-shadow:var(--shadow)}
.af2 .af2-kpi::after{content:"";position:absolute;right:-28px;top:-32px;
  width:96px;height:96px;border-radius:50%;background:var(--ks,rgba(213,0,28,.07))}
.af2 .af2-kpi-top{position:relative;z-index:1;display:flex;align-items:center;
  justify-content:space-between;gap:10px}
.af2 .af2-kpi-icon{width:36px;height:36px;border-radius:10px;display:grid;
  place-items:center;color:var(--kc,var(--red));background:var(--ks,rgba(213,0,28,.08))}
.af2 .af2-kpi-icon svg{width:18px;height:18px}
.af2 .af2-kpi small{color:#7c8189;font-size:11px;font-weight:750}
.af2 .af2-kpi-val{position:relative;z-index:1;margin-top:12px;font-size:28px;
  line-height:1;letter-spacing:-.04em;font-weight:900}
.af2 .af2-kpi-lbl{position:relative;z-index:1;margin-top:6px;
  color:#686d75;font-size:12px;font-weight:650}
/* grid */
.af2 .af2-grid{display:grid;grid-template-columns:1.1fr .9fr .95fr;
  gap:16px;margin-bottom:18px}
.af2 .af2-card{min-width:0;background:#fff;border:1px solid var(--line);
  border-radius:var(--radius);box-shadow:var(--shadow)}
.af2 .af2-card-head{display:flex;align-items:flex-start;justify-content:space-between;
  gap:12px;padding:17px 18px 10px}
.af2 .af2-card-head h3{margin:0;font-size:14px;letter-spacing:-.015em}
.af2 .af2-card-head p{margin:4px 0 0;color:#858990;font-size:11px}
.af2 .af2-badge{padding:6px 9px;border-radius:999px;color:#5f646c;
  background:#f4f5f6;font-size:10px;font-weight:800;white-space:nowrap}
.af2 .af2-card-body{padding:8px 18px 18px}
/* donut */
.af2 .af2-rl{display:grid;grid-template-columns:148px minmax(0,1fr);
  gap:18px;align-items:center;min-height:210px}
.af2 .af2-donut{width:136px;height:136px;border-radius:50%;
  background:conic-gradient(#d5001c 0 40%,#ef6b2e 40% 65%,#d58a13 65% 82%,
  #7157c8 82% 94%,#15171b 94% 100%);
  position:relative;display:grid;place-items:center;margin:auto}
.af2 .af2-donut::after{content:"";position:absolute;width:86px;height:86px;
  border-radius:50%;background:#fff;box-shadow:0 0 0 1px var(--line)}
.af2 .af2-dc{position:relative;z-index:2;text-align:center}
.af2 .af2-dc strong{display:block;font-size:22px;line-height:1;font-weight:900}
.af2 .af2-dc span{display:block;margin-top:5px;color:#80848b;font-size:10px}
.af2 .af2-leg{display:grid;gap:9px}
.af2 .af2-lr{display:grid;grid-template-columns:8px minmax(0,1fr) auto;
  align-items:center;gap:8px;font-size:11px}
.af2 .af2-lr i{width:8px;height:8px;border-radius:3px}
.af2 .af2-lr span{color:#686d75}
/* bars */
.af2 .af2-bars{display:grid;gap:10px}
.af2 .af2-dept-scroll{max-height:250px;overflow:auto;padding:8px 18px 18px}
.af2 .af2-dept-scroll::-webkit-scrollbar{width:5px}
.af2 .af2-dept-scroll::-webkit-scrollbar-thumb{background:#d5d8dc;border-radius:999px}
.af2 .af2-br{display:grid;gap:5px}
.af2 .af2-bm{display:flex;align-items:center;justify-content:space-between;
  gap:10px;font-size:11px}
.af2 .af2-bm span{color:#5f646b;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.af2 .af2-bm strong{font-size:11px;white-space:nowrap}
.af2 .af2-bt{height:8px;border-radius:999px;background:#f0f1f3;overflow:hidden}
.af2 .af2-bf{height:100%;border-radius:999px;
  background:linear-gradient(90deg,var(--red),#ff3f56);
  transform-origin:left;animation:af2grow .6s ease both}
@keyframes af2grow{from{transform:scaleX(0)}to{transform:scaleX(1)}}
/* types */
.af2 .af2-types{display:grid;gap:9px}
.af2 .af2-ti{display:grid;grid-template-columns:38px minmax(0,1fr) auto;
  gap:10px;align-items:center;padding:9px 10px;
  border:1px solid #eceef0;border-radius:12px;background:#fbfbfc}
.af2 .af2-tico{width:34px;height:34px;border-radius:10px;display:grid;
  place-items:center;background:#fff0f2;color:var(--red);font-size:14px;font-weight:900}
.af2 .af2-ti span{font-size:11px;color:#545961;font-weight:700}
.af2 .af2-ti strong{font-size:15px}
/* second grid */
.af2 .af2-grid2{display:grid;grid-template-columns:1fr 1.8fr;gap:16px;margin-bottom:18px}
.af2 .af2-trend-wrap{padding:4px 18px 18px}
.af2 .af2-svg{width:100%;height:220px;display:block;overflow:visible}
.af2 .af2-gl{stroke:#eceef0;stroke-width:1}
.af2 .af2-area{fill:url(#af2Grad)}
.af2 .af2-line{fill:none;stroke:var(--red);stroke-width:3;stroke-linecap:round;stroke-linejoin:round}
.af2 .af2-dot{fill:#fff;stroke:var(--red);stroke-width:3}
.af2 .af2-al{fill:#8a8e95;font-size:10px}
.af2 .af2-vl{fill:#292d32;font-size:10px;font-weight:800}
/* responsive */
@media(max-width:1200px){
  .af2 .af2-filters{grid-template-columns:repeat(3,minmax(130px,1fr))}
  .af2 .af2-grid{grid-template-columns:1fr 1fr}
  .af2 .af2-grid .af2-card:last-child{grid-column:1/-1}
  .af2 .af2-grid2{grid-template-columns:1fr}}
@media(max-width:860px){
  .af2 .af2-filters{grid-template-columns:1fr 1fr}
  .af2 .af2-kpis{grid-template-columns:repeat(2,1fr)}
  .af2 .af2-grid,.af2 .af2-grid2{grid-template-columns:1fr}
  .af2 .af2-grid .af2-card:last-child{grid-column:auto}}
@media(max-width:560px){
  .af2 .af2-filters{grid-template-columns:1fr}
  .af2 .af2-kpis{grid-template-columns:1fr}
  .af2 .af2-rl{grid-template-columns:1fr}}
</style>"""

    html_main = """<div class="af2">
<div class="af2-hero">
  <div>
    <h2>Painel de saúde ocupacional</h2>
    <p>Acompanhe frequência, duração, concentração e evolução dos afastamentos.</p>
  </div>
  <div class="af2-updated"><i></i>Dados atualizados</div>
</div>

<section class="af2-filters">
  <div class="af2-field"><label>Empresa</label>
    <div class="af2-sw"><select id="af2Company"></select></div></div>
  <div class="af2-field"><label>Departamento</label>
    <div class="af2-sw"><select id="af2Dept"></select></div></div>
  <div class="af2-field"><label>Tipo</label>
    <div class="af2-sw"><select id="af2Type"></select></div></div>
  <div class="af2-field"><label>Ano</label>
    <div class="af2-sw"><select id="af2Year"></select></div></div>
  <div class="af2-field"><label>Mês</label>
    <div class="af2-sw"><select id="af2Month"></select></div></div>
  <div class="af2-field"><label>Faixa de dias</label>
    <div class="af2-sw"><select id="af2Range">
      <option value="">Todas as faixas</option>
      <option value="1 dia">1 dia</option>
      <option value="2–3 dias">2–3 dias</option>
      <option value="4–7 dias">4–7 dias</option>
      <option value="8–15 dias">8–15 dias</option>
      <option value="16+ dias">16+ dias</option>
    </select></div></div>
  <button class="af2-reset" onclick="af2Reset()">Limpar</button>
</section>

<section class="af2-kpis">
  <article class="af2-kpi" style="--kc:#d5001c;--ks:rgba(213,0,28,.08)">
    <div class="af2-kpi-top">
      <div class="af2-kpi-icon">
        <svg fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24">
          <rect x="3" y="4" width="18" height="17" rx="2"/><path d="M8 2v4m8-4v4M3 10h18"/>
        </svg>
      </div><small>Ocorrências</small>
    </div>
    <div class="af2-kpi-val" id="af2KR">—</div>
    <div class="af2-kpi-lbl">Registros</div>
  </article>
  <article class="af2-kpi" style="--kc:#7157c8;--ks:rgba(113,87,200,.10)">
    <div class="af2-kpi-top">
      <div class="af2-kpi-icon">
        <svg fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24">
          <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/><path d="M9 12h6M12 9v6"/>
        </svg>
      </div><small>Com período</small>
    </div>
    <div class="af2-kpi-val" id="af2KL">—</div>
    <div class="af2-kpi-lbl">Com afastamento</div>
  </article>
  <article class="af2-kpi" style="--kc:#15966a;--ks:rgba(21,150,106,.10)">
    <div class="af2-kpi-top">
      <div class="af2-kpi-icon">
        <svg fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24">
          <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/>
          <circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/>
        </svg>
      </div><small>Pessoas</small>
    </div>
    <div class="af2-kpi-val" id="af2KP">—</div>
    <div class="af2-kpi-lbl">Colaboradores únicos</div>
  </article>
  <article class="af2-kpi" style="--kc:#d58a13;--ks:rgba(213,138,19,.11)">
    <div class="af2-kpi-top">
      <div class="af2-kpi-icon">
        <svg fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24">
          <circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>
        </svg>
      </div><small>Impacto</small>
    </div>
    <div class="af2-kpi-val" id="af2KD">—</div>
    <div class="af2-kpi-lbl">Dias afastados (total)</div>
  </article>
  <article class="af2-kpi" style="--kc:#ef6b2e;--ks:rgba(239,107,46,.10)">
    <div class="af2-kpi-top">
      <div class="af2-kpi-icon">
        <svg fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24">
          <path d="M4 19V9m5 10V5m5 14v-7m5 7V3"/>
        </svg>
      </div><small>Duração</small>
    </div>
    <div class="af2-kpi-val" id="af2KA">—</div>
    <div class="af2-kpi-lbl">Média de dias / ocorrência</div>
  </article>
</section>

<section class="af2-grid">
  <article class="af2-card">
    <div class="af2-card-head">
      <div><h3>Faixa de dias afastados</h3><p>Distribuição por duração</p></div>
      <span class="af2-badge" id="af2RT">— ocorrências</span>
    </div>
    <div class="af2-card-body af2-rl">
      <div class="af2-donut" id="af2Donut">
        <div class="af2-dc"><strong id="af2DT">—</strong><span>registros</span></div>
      </div>
      <div class="af2-leg" id="af2Leg"></div>
    </div>
  </article>

  <article class="af2-card">
    <div class="af2-card-head">
      <div><h3>Por departamento</h3><p>Top 10 áreas com mais ocorrências</p></div>
      <span class="af2-badge">Ranking</span>
    </div>
    <div class="af2-dept-scroll">
      <div class="af2-bars" id="af2DeptBars"></div>
    </div>
  </article>

  <article class="af2-card">
    <div class="af2-card-head">
      <div><h3>Por tipo de atestado</h3><p>Composição dos registros filtrados</p></div>
      <span class="af2-badge">Classificação</span>
    </div>
    <div class="af2-card-body">
      <div class="af2-types" id="af2Types"></div>
    </div>
  </article>
</section>

<section class="af2-grid2">
  <article class="af2-card">
    <div class="af2-card-head">
      <div><h3>Evolução mensal</h3><p>Ocorrências por mês</p></div>
      <span class="af2-badge" id="af2TY">—</span>
    </div>
    <div class="af2-trend-wrap" id="af2Trend"></div>
  </article>
  <article class="af2-card">
    <div class="af2-card-head">
      <div><h3>Leitura de criticidade</h3><p>Concentração por área e duração</p></div>
      <span class="af2-badge">Atenção ≥ 8 dias</span>
    </div>
    <div class="af2-card-body">
      <div class="af2-bars" id="af2Crit"></div>
    </div>
  </article>
</section>
</div>"""

    js_code = r"""
const AF2_COLORS = ["#d5001c","#ef6b2e","#d58a13","#7157c8","#15171b"];
const AF2_RANGES = ["1 dia","2–3 dias","4–7 dias","8–15 dias","16+ dias"];
const AF2_ICONS  = {"Médico":"✚","Odontológico":"◉","Declaração de Horas":"⌚","Saúde Ocupacional":"◇","Saúde":"♡"};

function af2El(id){return document.getElementById(id)}
function af2Uniq(arr,k){return[...new Set(arr.map(x=>x[k]).filter(Boolean))].sort((a,b)=>String(a).localeCompare(String(b),"pt-BR"))}
function af2RangeOf(d){if(d===1)return AF2_RANGES[0];if(d<=3)return AF2_RANGES[1];if(d<=7)return AF2_RANGES[2];if(d<=15)return AF2_RANGES[3];return AF2_RANGES[4]}
function af2TitleCase(s){return s?s.split(" ").map(w=>w?w[0].toUpperCase()+w.slice(1).toLowerCase():"").join(" "):""}

function af2FillSel(id,vals,lbl){
  const el=af2El(id);if(!el)return;
  el.innerHTML='<option value="">'+lbl+'</option>'+vals.map(v=>'<option value="'+v+'">'+v+'</option>').join("")
}

function af2Setup(){
  af2FillSel("af2Company",af2Uniq(af2Records,"company"),"Todas as empresas");
  af2FillSel("af2Dept",af2Uniq(af2Records,"department"),"Todos os departamentos");
  af2FillSel("af2Type",af2Uniq(af2Records,"type"),"Todos os tipos");
  af2FillSel("af2Year",[...new Set(af2Records.map(r=>r.date.slice(0,4)).filter(Boolean))].sort().reverse(),"Todos os anos");
  /* lista, e nao objeto: chaves "10".."12" sao indices validos e o JS as
     reordenaria para o inicio, colocando Out/Nov/Dez antes de Jan */
  const AF2_MESES=[["01","Jan"],["02","Fev"],["03","Mar"],["04","Abr"],
                   ["05","Mai"],["06","Jun"],["07","Jul"],["08","Ago"],
                   ["09","Set"],["10","Out"],["11","Nov"],["12","Dez"]];
  const elM=af2El("af2Month");
  if(elM){
    elM.innerHTML='<option value="">Todos os meses</option>'+
      AF2_MESES.map(m=>'<option value="'+m[0]+'">'+m[1]+'</option>').join("");
  }
  ["af2Company","af2Dept","af2Type","af2Year","af2Month","af2Range"].forEach(id=>{
    const el=af2El(id);if(el)el.addEventListener("change",af2Render);
  });
}

function af2Filtered(){
  const co=af2El("af2Company")?.value||"",de=af2El("af2Dept")?.value||"",
        ty=af2El("af2Type")?.value||"",yr=af2El("af2Year")?.value||"",
        mo=af2El("af2Month")?.value||"",
        rg=af2El("af2Range")?.value||"";
  return af2Records.filter(r=>
    (!co||r.company===co)&&(!de||r.department===de)&&
    (!ty||r.type===ty)&&(!yr||r.date.startsWith(yr))&&
    (!mo||r.date.slice(5,7)===mo)&&
    (!rg||af2RangeOf(r.days)===rg));
}

function af2KPIs(data){
  const tot=data.length,days=data.reduce((s,r)=>s+r.days,0);
  const avg=tot?(days/tot).toFixed(1).replace(".",","):"0,0";
  const set=el=>({t,v})=>{const x=af2El(el);if(x)x.textContent=v};
  if(af2El("af2KR"))af2El("af2KR").textContent=tot;
  if(af2El("af2KL"))af2El("af2KL").textContent=data.filter(r=>r.start&&r.end).length;
  if(af2El("af2KP"))af2El("af2KP").textContent=new Set(data.map(r=>r.id)).size;
  if(af2El("af2KD"))af2El("af2KD").textContent=days;
  if(af2El("af2KA"))af2El("af2KA").textContent=avg;
}

function af2Ranges(data){
  const cnt=Object.fromEntries(AF2_RANGES.map(k=>[k,0]));
  data.forEach(r=>cnt[af2RangeOf(r.days)]++);
  const tot=data.length||1;
  const pct=AF2_RANGES.map(k=>cnt[k]/tot*100);
  let acc=0;const stops=pct.map(v=>{acc+=v;return acc});
  const dn=af2El("af2Donut");
  if(dn)dn.style.background="conic-gradient("+
    AF2_COLORS[0]+" 0 "+stops[0].toFixed(2)+"%, "+
    AF2_COLORS[1]+" "+stops[0].toFixed(2)+"% "+stops[1].toFixed(2)+"%, "+
    AF2_COLORS[2]+" "+stops[1].toFixed(2)+"% "+stops[2].toFixed(2)+"%, "+
    AF2_COLORS[3]+" "+stops[2].toFixed(2)+"% "+stops[3].toFixed(2)+"%, "+
    AF2_COLORS[4]+" "+stops[3].toFixed(2)+"% 100%)";
  const dt=af2El("af2DT");if(dt)dt.textContent=data.length;
  const rt=af2El("af2RT");if(rt)rt.textContent=data.length+" ocorrências";
  const leg=af2El("af2Leg");
  if(leg)leg.innerHTML=AF2_RANGES.map((k,i)=>
    '<div class="af2-lr"><i style="background:'+AF2_COLORS[i]+'"></i>'+
    '<span>'+k+'</span><strong>'+cnt[k]+
    ' &middot; '+(data.length?Math.round(cnt[k]/data.length*100):0)+'%</strong></div>').join("");
}

function af2Depts(data){
  const map={};
  data.forEach(r=>{const k=af2TitleCase(r.department||"");map[k]=(map[k]||0)+1});
  const rows=Object.entries(map).sort((a,b)=>b[1]-a[1]).slice(0,10);
  const max=rows[0]?.[1]||1;
  const el=af2El("af2DeptBars");
  if(!el)return;
  el.innerHTML=rows.length?rows.map(([n,v])=>
    '<div class="af2-br"><div class="af2-bm"><span title="'+n+'">'+n+'</span>'+
    '<strong>'+v+'</strong></div>'+
    '<div class="af2-bt"><div class="af2-bf" style="width:'+(v/max*100).toFixed(1)+'%"></div></div>'+
    '</div>').join(""):'<p style="color:#888;font-size:12px;padding:8px 0">Sem dados</p>';
}

function af2Types(data){
  const map={};data.forEach(r=>map[r.type]=(map[r.type]||0)+1);
  const el=af2El("af2Types");if(!el)return;
  el.innerHTML=Object.entries(map).sort((a,b)=>b[1]-a[1]).map(([k,v])=>
    '<div class="af2-ti"><div class="af2-tico">'+(AF2_ICONS[k]||"•")+'</div>'+
    '<span>'+k+'</span><strong>'+v+'</strong></div>').join("")||
    '<p style="color:#888;font-size:12px">Sem dados</p>';
}

function af2Trend(data){
  const MN=["Jan","Fev","Mar","Abr","Mai","Jun","Jul","Ago","Set","Out","Nov","Dez"];
  const vals=Array(12).fill(0);
  data.forEach(r=>{if(r.date)vals[+r.date.slice(5,7)-1]++});
  const yr=af2El("af2Year")?.value||new Date().getFullYear().toString();
  const ty=af2El("af2TY");if(ty)ty.textContent=yr;
  const W=580,H=210,pl=14,pr=12,pt=16,pb=30;
  const max=Math.max(3,...vals);
  const xf=i=>pl+i*((W-pl-pr)/11);
  const yf=v=>H-pb-v*((H-pt-pb)/max);
  const pts=vals.map((v,i)=>xf(i)+","+yf(v)).join(" ");
  const aPts=pl+","+(H-pb)+" "+pts+" "+xf(11)+","+(H-pb);
  const dots=vals.map((v,i)=>
    '<circle class="af2-dot" cx="'+xf(i)+'" cy="'+yf(v)+'" r="4"/>'+
    (v?'<text class="af2-vl" x="'+xf(i)+'" y="'+(yf(v)-9)+'" text-anchor="middle">'+v+'</text>':"")
  ).join("");
  const lbls=MN.map((m,i)=>'<text class="af2-al" x="'+xf(i)+'" y="'+(H-7)+'" text-anchor="middle">'+m+'</text>').join("");
  const el=af2El("af2Trend");if(!el)return;
  el.innerHTML='<svg class="af2-svg" viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="none">'+
    '<defs><linearGradient id="af2Grad" x1="0" y1="0" x2="0" y2="1">'+
    '<stop offset="0%" stop-color="#d5001c" stop-opacity=".22"/>'+
    '<stop offset="100%" stop-color="#d5001c" stop-opacity=".02"/></linearGradient></defs>'+
    '<polygon class="af2-area" points="'+aPts+'"/>'+
    '<polyline class="af2-line" points="'+pts+'"/>'+dots+lbls+'</svg>';
}

function af2Critical(data){
  const map={};
  data.filter(r=>r.days>=8).forEach(r=>{
    const k=af2TitleCase(r.department||"");
    if(!map[k])map[k]={occ:0,days:0};
    map[k].occ++;map[k].days+=r.days;
  });
  const rows=Object.entries(map).sort((a,b)=>b[1].days-a[1].days);
  const max=rows[0]?.[1].days||1;
  const el=af2El("af2Crit");if(!el)return;
  el.innerHTML=rows.length?rows.map(([n,v])=>
    '<div class="af2-br"><div class="af2-bm"><span title="'+n+'">'+n+'</span>'+
    '<strong>'+v.days+' dias &middot; '+v.occ+' ocorr.</strong></div>'+
    '<div class="af2-bt"><div class="af2-bf" style="width:'+(v.days/max*100).toFixed(1)+
    '%;background:linear-gradient(90deg,#17191d,#d5001c)"></div></div></div>').join(""):
    '<p style="color:#888;font-size:12px;padding:8px 0">Nenhum afastamento crítico no recorte.</p>';
}

function af2Render(){
  const d=af2Filtered();
  af2KPIs(d);af2Ranges(d);af2Depts(d);af2Types(d);af2Trend(d);af2Critical(d);
}

function af2Reset(){
  ["af2Company","af2Dept","af2Type","af2Year","af2Month","af2Range"].forEach(id=>{
    const el=af2El(id);if(el)el.value="";});
  af2Render();
}

af2Setup();af2Render();
"""

    return (
        f"<script>const af2Records={records_js};</script>"
        + css + html_main
        + "<script>" + js_code + "</script>"
    )




@router.get("/indicadores/afastamentos")
def afastamentos_indicador(
    request: Request,
    empresa: str = "",
    departamento: str = "",
    tipo: str = "",
    ano: str = "",
):
    from app.database import engine as _eng

    with _eng.connect() as conn:
        rows_raw = conn.execute(
            text("SELECT * FROM atestados_medicos ORDER BY id DESC")
        ).mappings().all()

    rows = []
    for r in rows_raw:
        d = dict(r)
        data_at  = _parse_dt_afas(d.get("data_atestado"))
        data_ini = _parse_dt_afas(d.get("data_inicio_afastamento"))
        data_fim = _parse_dt_afas(d.get("data_fim_afastamento"))
        dias = None
        if data_ini and data_fim:
            dias = max((data_fim - data_ini).days + 1, 0)
        rows.append({
            "id":                      d["id"],
            "empresa":                 str(d.get("empresa") or "").strip(),
            "departamento":            str(d.get("departamento") or "").strip(),
            "matricula":               str(d.get("matricula") or "").strip(),
            "nome_colaborador":        str(d.get("nome_colaborador") or "").strip(),
            "cargo":                   str(d.get("cargo") or "").strip(),
            "tipo_atestado":           str(d.get("tipo_atestado") or "").strip(),
            "cid":                     str(d.get("cid") or "").strip(),
            "data_atestado":           str(d.get("data_atestado") or "").strip(),
            "data_inicio_afastamento": str(d.get("data_inicio_afastamento") or "").strip(),
            "data_fim_afastamento":    str(d.get("data_fim_afastamento") or "").strip(),
            "dias":                    dias,
            "ano":                     str(data_at.year) if data_at else "",
            "mes":                     data_at.month if data_at else 0,
            "mes_nome":                _MESES_PT_AFAS[data_at.month - 1] if data_at else "",
        })

    dash_html = _build_afastamentos_html(rows)
    return templates.TemplateResponse("indicadores/afastamentos.html", {
        "request":   request,
        "dash_html": dash_html,
    })
