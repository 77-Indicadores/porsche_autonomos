"""Módulo Indicadores — dashboards analíticos com dados do Feedz via OData."""

from __future__ import annotations

import calendar
import os
from collections import defaultdict
from datetime import date, datetime
from typing import Optional

import requests
from fastapi import APIRouter, Request

from app.template_config import templates

router = APIRouter(tags=["indicadores"])

# ─── OData ────────────────────────────────────────────────────────────────────

def _fetch_feedz(entity: str) -> list[dict]:
    base_url = os.getenv("FEEDZ_ODATA_URL", "https://catworld.77indicadores.com.br/api/odata/porsche/feedz")
    token = os.getenv("FEEDZ_TOKEN", "")
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
        result.append({
            "nome": nome,
            "data_adm": data_adm,
            "data_demissa": data_demissa,
            "situacao": str(r.get("situacao") or "").strip() or "Não informado",
            "tipo_de_vinculo": str(r.get("tipo_de_vinculo") or "").strip() or "Não informado",
            "sexo": str(r.get("sexo") or "").strip() or "Não informado",
            "unidade": str(r.get("unidade") or "").strip() or "Não informado",
            "grau_de_instrucao": str(r.get("grau_de_instrucao") or "").strip() or "Não informado",
        })
    return result


def _is_ativo(c: dict, ref: date) -> bool:
    adm, dem = c["data_adm"], c["data_demissa"]
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
    result = []
    for i in range(5, -1, -1):
        ano, mes = ref.year, ref.month - i
        while mes <= 0:
            mes += 12; ano -= 1
        fim = _eomonth(date(ano, mes, 1))
        total = sum(1 for c in colabs if _is_ativo(c, fim))
        result.append((fim, _mes_label_upper(fim), total))
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
.filter{
  min-width:160px;background:rgba(255,255,255,.88);
  border:1px solid rgba(0,0,0,.07);border-radius:14px;
  padding:9px 12px;box-shadow:var(--shadow-soft);
}
.filter label{display:block;font-size:10px;color:#8b8f94;text-transform:uppercase;letter-spacing:.09em;font-weight:800;margin-bottom:4px}
.filter select{width:100%;border:0;background:transparent;outline:none;color:#252525;font-size:13px;font-weight:700;cursor:pointer}
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
    <div class="filter">
      <label>Competência</label>
      <form method="get" style="margin:0">
        <select name="mes" onchange="this.form.submit()" class=""
          style="width:100%;border:0;background:transparent;outline:none;color:#252525;font-size:13px;font-weight:700;cursor:pointer">
          {opts}
        </select>
      </form>
    </div>
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


# ─── rotas ────────────────────────────────────────────────────────────────────

@router.get("/indicadores")
def indicadores_home(request: Request):
    return templates.TemplateResponse("indicadores/index.html", {"request": request})


@router.get("/indicadores/headcount")
def headcount(request: Request, mes: str = ""):
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
        colabs = _normalizar_colabs(rows)
        dash_html = _build_headcount_html(colabs, ref, meses_opcoes, mes_sel)
    except Exception as exc:
        erro = f"Erro ao buscar dados do Feedz: {exc}"

    return templates.TemplateResponse("indicadores/headcount.html", {
        "request": request,
        "dash_html": dash_html,
        "erro": erro,
    })
