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
.dash{font-family:Segoe UI,Arial,sans-serif;background:#F5F5F2;padding:15px 18px;border-radius:17px;
color:#1A1A1A;border:1px solid #E5E5E0;box-sizing:border-box;width:100%}
.header{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;
padding-bottom:10px;border-bottom:3px solid #E30613}
.title{font-size:22px;font-weight:800;color:#1A1A1A;letter-spacing:-0.3px;line-height:1.1}
.subtitle{font-size:12px;color:#4A4A4A;margin-top:4px}
.header-right{display:flex;gap:10px;align-items:stretch;flex-wrap:wrap}
.kpi{background:#1A1A1A;color:#FFF;padding:12px 22px;border-radius:15px;min-width:162px;
text-align:right;box-shadow:0 9px 20px rgba(26,26,26,.20);border-bottom:4px solid #E30613;
display:flex;flex-direction:column;justify-content:center}
.kpi-value{font-size:34px;font-weight:800;line-height:1}
.kpi-label{font-size:12px;color:#F5F5F2;opacity:.95;margin-top:5px}
.kpi-mini{background:#FFF;border:1px solid #E5E5E0;border-radius:15px;padding:11px 18px;
min-width:88px;text-align:center;box-shadow:0 6px 16px rgba(26,26,26,.075);
border-bottom:4px solid #E30613;display:flex;flex-direction:column;justify-content:center}
.kpi-mini-value{font-size:27px;font-weight:800;color:#1A1A1A;line-height:1}
.kpi-mini-label{font-size:10.5px;color:#4A4A4A;margin-top:5px;font-weight:600}
.evol-card{background:#FFF;border-radius:15px;padding:13px 16px 8px;
box-shadow:0 6px 16px rgba(26,26,26,.075);border:1px solid #E5E5E0;
position:relative;overflow:hidden;margin-bottom:12px;box-sizing:border-box}
.evol-card:before{content:'';position:absolute;top:0;left:0;width:100%;height:3px;background:#E30613}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
.card{background:#FFF;border-radius:15px;padding:13px;box-shadow:0 6px 16px rgba(26,26,26,.075);
border:1px solid #E5E5E0;position:relative;overflow:hidden;box-sizing:border-box}
.card:before{content:'';position:absolute;top:0;left:0;width:100%;height:3px;background:#E30613}
.card-title{font-size:13.5px;font-weight:800;margin-bottom:2px;color:#1A1A1A;
display:flex;justify-content:space-between;align-items:center;gap:6px;line-height:1.1}
.card-subtitle{font-size:9.5px;color:#8A8A8A;margin-bottom:8px}
.badge{font-size:9.5px;font-weight:700;color:#FFF;background:#1A1A1A;
padding:2px 7px;border-radius:999px;white-space:nowrap}
.row{display:grid;grid-template-columns:98px 1fr 54px;align-items:center;gap:7px;margin-bottom:6.5px}
.label{font-size:11px;color:#4A4A4A;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.value{font-size:10.5px;text-align:right;color:#1A1A1A;white-space:nowrap}
.num{font-weight:800}
.pct{font-size:9px;font-weight:600;color:#7A7A7A}
.bar-wrap{width:100%;height:7px;background:#F5F5F2;border-radius:999px;overflow:hidden;border:1px solid #E5E5E0}
.bar{height:7px;background:#E30613;border-radius:999px}
.footer{margin-top:8px;font-size:10px;color:#4A4A4A;line-height:1.15}
@media(max-width:900px){.grid{grid-template-columns:repeat(2,1fr)}}
@media(max-width:550px){.grid{grid-template-columns:1fr}.header{flex-direction:column;gap:10px}}
</style>
"""


def _html_barras(itens: list[tuple[str, int]], total: int) -> str:
    partes = []
    for label, valor in itens:
        pct = valor / total * 100 if total else 0
        partes.append(
            f"<div class='row'>"
            f"<div class='label'>{label}</div>"
            f"<div class='bar-wrap'><div class='bar' style='width:{pct:.0f}%'></div></div>"
            f"<div class='value'><span class='num'>{valor:,}</span>"
            f"<span class='pct'> - {pct:.1f}%</span></div>"
            f"</div>"
        )
    return "".join(partes)


def _html_evolucao(evolucao: list[tuple[str, int]]) -> str:
    n = len(evolucao)
    if n == 0:
        return ""
    max_val = max(v for _, v in evolucao) or 1

    pontos_xy = []
    for i, (label, val) in enumerate(evolucao):
        x = 55 + i * (1050 / (n - 1)) if n > 1 else 580
        y = 112 - (val / max_val) * 86
        pontos_xy.append((x, y, label, val))

    pontos_str = " ".join(f"{x:.0f},{y:.0f}" for x, y, _, _ in pontos_xy)
    area_str = f"55,112 {pontos_str} 1105,112"

    dots = ""
    for x, y, label, val in pontos_xy:
        dots += (
            f"<circle cx='{x:.0f}' cy='{y:.0f}' r='4' fill='#FFF' stroke='#E30613' stroke-width='2.5'/>"
            f"<text x='{x:.0f}' y='{y-10:.0f}' text-anchor='middle' font-size='13' font-weight='800' fill='#1A1A1A'>{val}</text>"
            f"<text x='{x:.0f}' y='136' text-anchor='middle' font-size='11' font-weight='700' fill='#8A8A8A'>{label}</text>"
        )

    return (
        f"<svg viewBox='0 0 1160 150' preserveAspectRatio='none' style='width:100%;height:120px;display:block;margin-top:6px'>"
        f"<defs><linearGradient id='evgrad' x1='0' y1='0' x2='0' y2='1'>"
        f"<stop offset='0%' stop-color='#E30613' stop-opacity='0.20'/>"
        f"<stop offset='100%' stop-color='#E30613' stop-opacity='0'/></linearGradient></defs>"
        f"<line x1='55' y1='26' x2='1105' y2='26' stroke='#EEEEEC' stroke-width='1'/>"
        f"<line x1='55' y1='69' x2='1105' y2='69' stroke='#EEEEEC' stroke-width='1'/>"
        f"<line x1='55' y1='112' x2='1105' y2='112' stroke='#EEEEEC' stroke-width='1'/>"
        f"<polyline points='{area_str}' fill='url(#evgrad)' stroke='none'/>"
        f"<polyline points='{pontos_str}' fill='none' stroke='#E30613' stroke-width='3' stroke-linecap='round' stroke-linejoin='round'/>"
        f"{dots}"
        f"</svg>"
    )


def _build_headcount_html(colabs: list[dict], ref: date, periodo_label: str) -> str:
    total_ativos = sum(1 for c in colabs if _is_ativo(c, ref))

    situacao = _contar_por_campo(colabs, "situacao", ref)
    vinculos = _contar_por_campo(colabs, "tipo_de_vinculo", ref)
    sexo = _contar_por_campo(colabs, "sexo", ref)
    unidade = _contar_por_campo(colabs, "unidade", ref)
    instrucao = _contar_por_campo(colabs, "grau_de_instrucao", ref)
    evolucao = _evolucao_6m(colabs, ref)

    kpi_mini = "".join(
        f"<div class='kpi-mini'>"
        f"<div class='kpi-mini-value'>{v:,}</div>"
        f"<div class='kpi-mini-label'>{l}</div>"
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
        f"<div class='card'>"
        f"<div class='card-title'>{titulo}<span class='badge'>Ativos</span></div>"
        f"<div class='card-subtitle'>Qtd · % do total</div>"
        f"{_html_barras(itens, total_ativos)}"
        f"</div>"
        for titulo, itens in cards
    )

    return (
        f"<div class='dash'>{_CSS}"
        f"<div class='header'>"
        f"<div><div class='title'>Headcount Ativo</div>"
        f"<div class='subtitle'>Porsche Carrera Cup Brasil / Sprint Challenge Brasil · Até {periodo_label}</div></div>"
        f"<div class='header-right'>"
        f"<div class='kpi'><div class='kpi-value'>{total_ativos:,}</div>"
        f"<div class='kpi-label'>Colaboradores ativos</div></div>"
        f"{kpi_mini}"
        f"</div></div>"
        f"<div class='evol-card'>"
        f"<div class='card-title'>Evolução Headcount Ativo<span class='badge'>6 meses</span></div>"
        f"<div class='card-subtitle'>Colaboradores ativos por mês</div>"
        f"{_html_evolucao(evolucao)}"
        f"</div>"
        f"<div class='grid'>{grid_html}</div>"
        f"<div class='footer'>Base calculada por todos os vínculos ativos, considerando a posição no último dia do período selecionado.</div>"
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

    try:
        rows = _fetch_feedz("rel_colab_77")
        colabs = _normalizar_colabs(rows)
        dash_html = _build_headcount_html(colabs, ref, periodo_label)
    except Exception as exc:
        erro = f"Erro ao buscar dados do Feedz: {exc}"

    # Gera lista de meses (12 meses para o seletor)
    hoje = date.today()
    meses_opcoes = []
    for i in range(11, -1, -1):
        ano = hoje.year
        m = hoje.month - i
        while m <= 0:
            m += 12
            ano -= 1
        meses_opcoes.append((f"{ano}-{m:02d}", _mes_label(date(ano, m, 1))))

    return templates.TemplateResponse("indicadores/headcount.html", {
        "request": request,
        "dash_html": dash_html,
        "erro": erro,
        "mes_sel": mes or f"{ref_base.year}-{ref_base.month:02d}",
        "meses_opcoes": meses_opcoes,
        "periodo_label": periodo_label,
    })
