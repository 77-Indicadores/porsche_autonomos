"""Módulo Indicadores — dashboards analíticos com dados do Feedz via OData."""

from __future__ import annotations

import calendar
import os
from collections import defaultdict
from datetime import date, datetime
from typing import Optional

import requests
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.template_config import templates

router = APIRouter(tags=["indicadores"])

# ─── OData helper ─────────────────────────────────────────────────────────────

def _fetch_feedz(entity: str) -> list[dict]:
    """Busca todos os registros de uma entidade OData do Feedz, tratando paginação."""
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


# ─── date helpers ─────────────────────────────────────────────────────────────

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
    last_day = calendar.monthrange(d.year, d.month)[1]
    return date(d.year, d.month, last_day)


def _mes_label(d: date) -> str:
    meses = ["JAN","FEV","MAR","ABR","MAI","JUN","JUL","AGO","SET","OUT","NOV","DEZ"]
    return f"{meses[d.month - 1]}/{str(d.year)[2:]}"


# ─── processamento headcount ──────────────────────────────────────────────────

def _normalizar_colabs(rows: list[dict]) -> list[dict]:
    """Normaliza colunas relevantes de cada colaborador."""
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


def _is_ativo(colab: dict, ref: date) -> bool:
    adm = colab["data_adm"]
    dem = colab["data_demissa"]
    if adm is None or adm > ref:
        return False
    return dem is None or dem > ref


def _contar_por_campo(colabs: list[dict], campo: str, ref: date) -> list[tuple[str, int]]:
    counts: dict[str, int] = defaultdict(int)
    for c in colabs:
        if _is_ativo(c, ref):
            counts[c[campo]] += 1
    return sorted(counts.items(), key=lambda x: -x[1])


def _evolucao_6m(colabs: list[dict], ref: date) -> list[tuple[str, int]]:
    meses = []
    for i in range(5, -1, -1):
        ano = ref.year
        mes = ref.month - i
        while mes <= 0:
            mes += 12
            ano -= 1
        fim = _eomonth(date(ano, mes, 1))
        total = sum(1 for c in colabs if _is_ativo(c, fim))
        meses.append((_mes_label(fim), total))
    return meses


# ─── geração HTML ─────────────────────────────────────────────────────────────

_CSS = """
<style>
*{box-sizing:border-box}
.hc-wrap{font-family:'Segoe UI',Arial,sans-serif;color:#111;width:100%}

/* ── topbar ── */
.hc-topbar{background:#111;color:#fff;border-radius:18px;padding:20px 28px;
  display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:16px;flex-wrap:wrap}
.hc-brand{display:flex;flex-direction:column;gap:2px}
.hc-brand-title{font-size:22px;font-weight:900;letter-spacing:-0.5px;line-height:1}
.hc-brand-sub{font-size:12px;color:#9ca3af;margin-top:2px}
.hc-period-form{display:flex;align-items:center;gap:10px}
.hc-select{background:#1f2937;border:1px solid #374151;color:#f9fafb;
  border-radius:10px;padding:8px 14px;font-size:14px;font-weight:700;cursor:pointer;outline:none}
.hc-btn{background:#E30613;color:#fff;border:none;border-radius:10px;
  padding:9px 18px;font-size:13px;font-weight:800;cursor:pointer}

/* ── kpi row ── */
.hc-kpi-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:16px}
.hc-kpi{border-radius:16px;padding:18px 20px;display:flex;flex-direction:column;gap:4px;
  position:relative;overflow:hidden}
.hc-kpi-main{background:#E30613;color:#fff}
.hc-kpi-sec{background:#fff;border:1px solid #e5e7eb;color:#111}
.hc-kpi-val{font-size:36px;font-weight:900;line-height:1}
.hc-kpi-main .hc-kpi-val{color:#fff}
.hc-kpi-sec .hc-kpi-val{color:#111}
.hc-kpi-lbl{font-size:11px;font-weight:700;opacity:.85;text-transform:uppercase;letter-spacing:.06em}

/* ── cards ── */
.hc-card{background:#fff;border-radius:16px;border:1px solid #e5e7eb;overflow:hidden}
.hc-card-head{padding:14px 18px 0;display:flex;justify-content:space-between;align-items:flex-start}
.hc-card-title{font-size:14px;font-weight:800;color:#111;line-height:1.2}
.hc-card-sub{font-size:11px;color:#9ca3af;margin-top:2px}
.hc-badge{background:#111;color:#fff;font-size:10px;font-weight:800;
  padding:3px 9px;border-radius:999px;white-space:nowrap}
.hc-card-body{padding:12px 18px 16px}

/* ── evolução ── */
.hc-evol{margin-bottom:16px}

/* ── barras ── */
.hc-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
.hc-row{display:grid;grid-template-columns:90px 1fr 68px;align-items:center;gap:8px;margin-bottom:8px}
.hc-lbl{font-size:11px;color:#374151;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.hc-bar-track{height:6px;background:#f3f4f6;border-radius:999px;overflow:hidden}
.hc-bar-fill{height:6px;background:#E30613;border-radius:999px}
.hc-val{font-size:11px;text-align:right;white-space:nowrap}
.hc-num{font-weight:800;color:#111}
.hc-pct{font-size:10px;color:#9ca3af}

/* ── footer ── */
.hc-footer{margin-top:12px;font-size:11px;color:#9ca3af}

@media(max-width:900px){.hc-grid{grid-template-columns:repeat(2,1fr)}}
@media(max-width:560px){.hc-grid{grid-template-columns:1fr}.hc-topbar{flex-direction:column;align-items:flex-start}}
</style>
"""


def _html_barras(itens: list[tuple[str, int]], total: int) -> str:
    partes = []
    for label, valor in itens:
        pct = valor / total * 100 if total else 0
        partes.append(
            f"<div class='hc-row'>"
            f"<div class='hc-lbl'>{label}</div>"
            f"<div class='hc-bar-track'><div class='hc-bar-fill' style='width:{pct:.0f}%'></div></div>"
            f"<div class='hc-val'><span class='hc-num'>{valor:,}</span> "
            f"<span class='hc-pct'>{pct:.0f}%</span></div>"
            f"</div>"
        )
    return "".join(partes)


def _html_evolucao(evolucao: list[tuple[str, int]]) -> str:
    n = len(evolucao)
    if n == 0:
        return ""
    max_val = max(v for _, v in evolucao) or 1
    min_val = min(v for _, v in evolucao)
    spread = max_val - min_val or 1

    W, H = 1160, 160
    pad_x, pad_y_top, pad_y_bot = 60, 30, 30

    pontos_xy = []
    for i, (label, val) in enumerate(evolucao):
        x = pad_x + i * ((W - 2 * pad_x) / (n - 1)) if n > 1 else W / 2
        y = pad_y_top + (1 - (val - min_val) / spread) * (H - pad_y_top - pad_y_bot)
        pontos_xy.append((x, y, label, val))

    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y, _, _ in pontos_xy)
    area = f"{pontos_xy[0][0]:.1f},{H - pad_y_bot} {pts} {pontos_xy[-1][0]:.1f},{H - pad_y_bot}"

    dots = ""
    for x, y, label, val in pontos_xy:
        dots += (
            f"<circle cx='{x:.1f}' cy='{y:.1f}' r='5' fill='#E30613' stroke='#fff' stroke-width='2.5'/>"
            f"<text x='{x:.1f}' y='{y - 12:.1f}' text-anchor='middle' font-size='14' font-weight='800' fill='#111'>{val}</text>"
            f"<text x='{x:.1f}' y='{H - 4}' text-anchor='middle' font-size='11' font-weight='700' fill='#9ca3af'>{label}</text>"
        )

    grid_lines = "".join(
        f"<line x1='{pad_x}' y1='{pad_y_top + i * (H - pad_y_top - pad_y_bot) / 3:.1f}' "
        f"x2='{W - pad_x}' y2='{pad_y_top + i * (H - pad_y_top - pad_y_bot) / 3:.1f}' "
        f"stroke='#f3f4f6' stroke-width='1'/>"
        for i in range(4)
    )

    return (
        f"<svg viewBox='0 0 {W} {H}' preserveAspectRatio='none' style='width:100%;height:140px;display:block'>"
        f"<defs><linearGradient id='eg' x1='0' y1='0' x2='0' y2='1'>"
        f"<stop offset='0%' stop-color='#E30613' stop-opacity='0.15'/>"
        f"<stop offset='100%' stop-color='#E30613' stop-opacity='0'/></linearGradient></defs>"
        f"{grid_lines}"
        f"<polygon points='{area}' fill='url(#eg)'/>"
        f"<polyline points='{pts}' fill='none' stroke='#E30613' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round'/>"
        f"{dots}"
        f"</svg>"
    )


def _html_periodo_opts(meses_opcoes: list[tuple[str, str]], mes_sel: str) -> str:
    opts = "".join(
        f"<option value='{v}'{' selected' if v == mes_sel else ''}>{l}</option>"
        for v, l in meses_opcoes
    )
    return opts


def _build_headcount_html(colabs: list[dict], ref: date, periodo_label: str,
                           meses_opcoes: list[tuple[str, str]], mes_sel: str) -> str:
    total_ativos = sum(1 for c in colabs if _is_ativo(c, ref))

    situacao = _contar_por_campo(colabs, "situacao", ref)
    vinculos = _contar_por_campo(colabs, "tipo_de_vinculo", ref)
    sexo = _contar_por_campo(colabs, "sexo", ref)
    unidade = _contar_por_campo(colabs, "unidade", ref)
    instrucao = _contar_por_campo(colabs, "grau_de_instrucao", ref)
    evolucao = _evolucao_6m(colabs, ref)

    kpi_situacao = "".join(
        f"<div class='hc-kpi hc-kpi-sec'>"
        f"<div class='hc-kpi-val'>{v:,}</div>"
        f"<div class='hc-kpi-lbl'>{l}</div>"
        f"</div>"
        for l, v in situacao
    )

    cards = [
        ("Tipo de vínculo", vinculos),
        ("Sexo", sexo),
        ("Unidade", unidade),
        ("Grau de instrução", instrucao),
    ]
    grid_html = "".join(
        f"<div class='hc-card'>"
        f"<div class='hc-card-head'>"
        f"<div><div class='hc-card-title'>{titulo}</div>"
        f"<div class='hc-card-sub'>Qtd · % do total</div></div>"
        f"<span class='hc-badge'>Ativos</span>"
        f"</div>"
        f"<div class='hc-card-body'>{_html_barras(itens, total_ativos)}</div>"
        f"</div>"
        for titulo, itens in cards
    )

    opts_html = _html_periodo_opts(meses_opcoes, mes_sel)

    return (
        f"<div class='hc-wrap'>{_CSS}"

        # topbar com seletor integrado
        f"<div class='hc-topbar'>"
        f"<div class='hc-brand'>"
        f"<div class='hc-brand-title'>Headcount Ativo</div>"
        f"<div class='hc-brand-sub'>Porsche Carrera Cup Brasil &amp; Sprint Challenge Brasil</div>"
        f"</div>"
        f"<form class='hc-period-form' method='get'>"
        f"<select class='hc-select' name='mes' onchange='this.form.submit()'>{opts_html}</select>"
        f"</form>"
        f"</div>"

        # kpi row
        f"<div class='hc-kpi-row'>"
        f"<div class='hc-kpi hc-kpi-main'>"
        f"<div class='hc-kpi-val'>{total_ativos:,}</div>"
        f"<div class='hc-kpi-lbl'>Colaboradores ativos · Até {periodo_label}</div>"
        f"</div>"
        f"{kpi_situacao}"
        f"</div>"

        # evolução
        f"<div class='hc-evol hc-card'>"
        f"<div class='hc-card-head'>"
        f"<div><div class='hc-card-title'>Evolução Headcount</div>"
        f"<div class='hc-card-sub'>Colaboradores ativos por mês</div></div>"
        f"<span class='hc-badge'>6 meses</span>"
        f"</div>"
        f"<div style='padding:8px 18px 4px'>{_html_evolucao(evolucao)}</div>"
        f"</div>"

        # grid de breakdowns
        f"<div class='hc-grid'>{grid_html}</div>"

        f"<div class='hc-footer'>Base calculada por todos os vínculos ativos, considerando a posição no último dia do período selecionado.</div>"
        f"</div>"
    )


# ─── rotas ────────────────────────────────────────────────────────────────────

@router.get("/indicadores")
def indicadores_home(request: Request):
    return templates.TemplateResponse("indicadores/index.html", {"request": request})


@router.get("/indicadores/headcount")
def headcount(request: Request, mes: str = ""):
    erro = None
    dash_html = ""

    # Determina período de referência
    if mes:
        try:
            ref_base = datetime.strptime(mes + "-01", "%Y-%m-%d").date()
        except ValueError:
            ref_base = date.today()
    else:
        ref_base = date.today()
    ref = _eomonth(ref_base)
    periodo_label = _mes_label(ref)
    mes_sel = mes or f"{ref_base.year}-{ref_base.month:02d}"

    # Gera lista de meses (12 meses para o seletor) — antes do try
    hoje = date.today()
    meses_opcoes = []
    for i in range(11, -1, -1):
        ano = hoje.year
        m = hoje.month - i
        while m <= 0:
            m += 12
            ano -= 1
        meses_opcoes.append((f"{ano}-{m:02d}", _mes_label(date(ano, m, 1))))

    try:
        rows = _fetch_feedz("rel_colab_77")
        colabs = _normalizar_colabs(rows)
        dash_html = _build_headcount_html(colabs, ref, periodo_label, meses_opcoes, mes_sel)
    except Exception as exc:
        erro = f"Erro ao buscar dados do Feedz: {exc}"

    return templates.TemplateResponse("indicadores/headcount.html", {
        "request": request,
        "dash_html": dash_html,
        "erro": erro,
        "mes_sel": mes_sel,
        "meses_opcoes": meses_opcoes,
        "periodo_label": periodo_label,
    })
