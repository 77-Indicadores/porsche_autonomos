"""Dashboards de Custo Pessoal — Folha de Pagamento.

Rotas com prioridade sobre as homônimas em indicadores.py
(registradas antes via main.py).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Request
from sqlalchemy import text

from app.database import engine
from app.template_config import templates

router = APIRouter(tags=["folha_custo"])


# ─── helpers ────────────────────────────────────────────────────────────────

def _db(sql: str, params: dict | None = None) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(text(sql), params or {}).mappings().all()
    return [dict(r) for r in rows]


def _brl(v, dec: int = 0) -> str:
    if v is None:
        v = 0
    v = round(float(v), dec)
    s = f"{abs(v):,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    prefix = "-R$ " if v < 0 else "R$ "
    return prefix + s


def _brl_k(v) -> str:
    """Formata em R$ k (milhares) para gráficos."""
    if v is None:
        v = 0
    v = float(v)
    if abs(v) >= 1_000_000:
        return f"R$ {v/1_000_000:.1f}M".replace(".", ",")
    if abs(v) >= 1_000:
        return f"R$ {v/1_000:.0f}k"
    return _brl(v)


# Classificação das verbas do budget_resultado (nomes limpos, match exato)
_CLASSIF_BUDGET: dict[str, str] = {
    "Salário":                  "Salário",
    "Hora Extra 50%":           "Adicionais",
    "Adicional Noturno":        "Adicionais",
    "Adicional 25%":            "Adicionais",
    "HE sobre Adicional 25%":   "Adicionais",
    "Apoiador Etapa":           "Adicionais",
    "Prêmio":                   "Adicionais",
    "Periculosidade":           "Adicionais",
    "Provisão Férias":          "Provisão",
    "Provisão 1/3 Férias":      "Provisão",
    "Provisão 13º Salário":     "Provisão",
    "Provisão Aviso Prévio":    "Provisão",
    "Provisão PLR":             "PLR",
    "GRRF":                     "Provisão",
    "FGTS":                     "Encargos",
    "INSS Patronal":            "Encargos",
    "Vale Refeição":            "Benefícios",
    "Vale Alimentação":         "Benefícios",
    "Vale Combustível":         "Benefícios",
    "Academia":                 "Benefícios",
    "Assistência Médica":       "Benefícios",
    "Assistência Odontológica": "Benefícios",
    "Seguro de Vida":           "Benefícios",
}

_EMOJI = {
    "Salário":    "💰",
    "Benefícios": "🎁",
    "Provisão":   "📦",
    "Adicionais": "⚡",
    "PLR":        "🏆",
    "Encargos":   "🏛️",
}


def _classif(desc: str) -> str:
    return _CLASSIF_BUDGET.get(desc, "Adicionais")


# ─── SVG helpers ─────────────────────────────────────────────────────────────

def _svg_percapita(empresas_data: list[dict]) -> str:
    """SVG de barras verticais mostrando custo per capita por empresa."""
    if not empresas_data:
        return ""
    n = len(empresas_data)
    W, H = 500, 210
    pad_l, pad_r = 30, 30
    pad_top, pad_bot = 58, 38
    chart_w = W - pad_l - pad_r
    chart_h = H - pad_top - pad_bot

    pc_vals = [d["total"] / d["hc"] if d["hc"] > 0 else 0 for d in empresas_data]
    vmax = max(pc_vals) if pc_vals else 1

    bar_w = min(72, chart_w / n * 0.55)
    spacing = chart_w / n

    parts = []
    for i, (d, pc) in enumerate(zip(empresas_data, pc_vals)):
        bh = max(4, chart_h * (pc / vmax)) if vmax > 0 else 4
        cx = pad_l + i * spacing + spacing / 2
        bx = cx - bar_w / 2
        by = pad_top + chart_h - bh
        nome = " ".join(d["nome"].split()[:2])[:16]
        parts.append(
            f"<rect x='{bx:.0f}' y='{by:.0f}' width='{bar_w:.0f}' height='{bh:.0f}' fill='#e10600' rx='4'/>"
            f"<text x='{cx:.0f}' y='{by-24:.0f}' text-anchor='middle' font-size='9' font-weight='700' fill='#111827'>"
            f"PCT {_brl(pc, 0)}</text>"
            f"<text x='{cx:.0f}' y='{by-12:.0f}' text-anchor='middle' font-size='9' fill='#6b7280'>HC {d['hc']}</text>"
            f"<text x='{cx:.0f}' y='{H-6:.0f}' text-anchor='middle' font-size='8' fill='#9ca3af'>{nome}</text>"
        )

    return f'<svg viewBox="0 0 {W} {H}" style="width:100%;display:block">{"".join(parts)}</svg>'


def _svg_line(pontos: list[tuple], labels: list[str], titulo: str = "") -> str:
    """SVG de linha com curva suave. pontos = [(label, valor), ...]"""
    n = len(pontos)
    if not n:
        return ""
    vals = [p[1] for p in pontos]
    vmax = max(vals) * 1.15 if any(v > 0 for v in vals) else 1

    W, H = 640, 290
    pad_l, pad_r = 50, 30
    pad_top, pad_bot = 52, 46
    chart_w = W - pad_l - pad_r
    chart_h = H - pad_top - pad_bot

    xs = [pad_l + i * chart_w / max(n - 1, 1) for i in range(n)]

    def fy(v):
        return pad_top + chart_h * (1 - v / max(vmax, 1))

    pts = [(xs[i], fy(p[1])) for i, p in enumerate(pontos)]

    def smooth_d(ps):
        if len(ps) < 2:
            return f"M{ps[0][0]:.1f},{ps[0][1]:.1f}"
        d = f"M{ps[0][0]:.1f},{ps[0][1]:.1f}"
        for i in range(1, len(ps)):
            x0, y0 = ps[i - 1]
            x1, y1 = ps[i]
            dx = (x1 - x0) / 3
            d += f" C{x0+dx:.1f},{y0:.1f} {x1-dx:.1f},{y1:.1f} {x1:.1f},{y1:.1f}"
        return d

    curve_d = smooth_d(pts)
    area_d = (curve_d
              + f" L{pts[-1][0]:.1f},{pad_top + chart_h:.1f}"
              + f" L{pts[0][0]:.1f},{pad_top + chart_h:.1f} Z")

    grad_id = f"ag{id(pontos) % 10000:04d}"

    grids = "".join(
        f'<line x1="{pad_l}" y1="{fy(vmax*f):.1f}" x2="{W-pad_r}" '
        f'y2="{fy(vmax*f):.1f}" stroke="#edf0f4" stroke-width="1"/>'
        for f in [0.25, 0.5, 0.75, 1.0]
    )

    circles = "".join(
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="6" fill="#ef3d57" stroke="#fff" stroke-width="3"/>'
        for x, y in pts
    )

    val_labels = "".join(
        f'<text x="{pts[i][0]:.0f}" y="{max(pts[i][1] - 11, 14):.0f}" '
        f'text-anchor="middle" font-size="11" fill="#5e6570" font-weight="600">'
        f'{_brl_k(p[1])}</text>'
        for i, p in enumerate(pontos)
    )

    x_labels = "".join(
        f'<text x="{xs[i]:.0f}" y="{H - 6}" text-anchor="middle" '
        f'font-size="11" fill="#747b87">{p[0]}</text>'
        for i, p in enumerate(pontos)
    )

    return f"""<svg viewBox="0 0 {W} {H}" style="width:100%;display:block;overflow:visible">
<defs>
  <linearGradient id="{grad_id}" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0%" stop-color="#ef3d57" stop-opacity=".18"/>
    <stop offset="100%" stop-color="#ef3d57" stop-opacity="0"/>
  </linearGradient>
</defs>
{grids}
<path d="{area_d}" fill="url(#{grad_id})"/>
<path d="{curve_d}" fill="none" stroke="#ef3d57" stroke-width="4"
  stroke-linecap="round" stroke-linejoin="round"
  style="filter:drop-shadow(0 5px 6px rgba(239,61,87,.18))"/>
{circles}
{val_labels}
{x_labels}
</svg>"""


# ─── queries compartilhadas ──────────────────────────────────────────────────

def _opcoes() -> tuple[list[str], list[str]]:
    empresas = [r["empresa_nome"] for r in _db(
        "SELECT DISTINCT empresa_nome FROM budget_resultado ORDER BY empresa_nome"
    )]
    comps = [r["competencia"] for r in _db(
        "SELECT DISTINCT competencia FROM budget_resultado ORDER BY competencia"
    )]
    return empresas, comps


def _where(empresa: str, comp_ini: str, comp_fim: str, prefix: str = "") -> tuple[str, dict]:
    conds, p = ["1=1"], {}
    if empresa:
        conds.append("empresa_nome = :empresa")
        p["empresa"] = empresa
    if comp_ini:
        conds.append("competencia >= :comp_ini")
        p["comp_ini"] = comp_ini
    if comp_fim:
        conds.append("competencia <= :comp_fim")
        p["comp_fim"] = comp_fim
    return " AND ".join(conds), p


# ═══════════════════════════════════════════════════════════════════════════
#  1. VISÃO CUSTO EMPRESA
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/indicadores/folha-visao-custo")
def folha_custo_empresa(
    request: Request,
    empresa: str = "",
    comp_ini: str = "",
    comp_fim: str = "",
):
    todas_empresas, todas_comps = _opcoes()

    where, params = _where(empresa, comp_ini, comp_fim)

    # KPIs totais
    kpi_row = _db(f"""
        SELECT
            SUM(valor_budget)                                               AS total,
            SUM(CASE WHEN descricao_verba IN ('FGTS','INSS Patronal')
                     THEN valor_budget ELSE 0 END)                          AS total_enc,
            COUNT(DISTINCT CASE WHEN descricao_verba = 'Salário'
                                THEN matricula END)                          AS hc
        FROM budget_resultado
        WHERE {where}
    """, params)
    kpi = kpi_row[0] if kpi_row else {}
    total_empresa = float(kpi.get("total") or 0)
    total_fgts    = float(kpi.get("total_enc") or 0)
    total_prov    = total_empresa - total_fgts
    headcount     = int(kpi.get("hc") or 0)

    # Verbas por classificação
    rub_rows = _db(f"""
        SELECT descricao_verba AS descricao, SUM(valor_budget) AS total
        FROM budget_resultado
        WHERE {where}
        GROUP BY descricao_verba
        ORDER BY total DESC
    """, params)

    classif_totais: dict[str, float] = {
        "Salário": 0, "Adicionais": 0, "Benefícios": 0,
        "Provisão": 0, "PLR": 0, "Encargos": 0,
    }
    classif_detalhe: dict[str, list[dict]] = {k: [] for k in classif_totais}
    for r in rub_rows:
        cat = _classif(r["descricao"])
        classif_totais[cat] = classif_totais.get(cat, 0) + float(r["total"] or 0)
        classif_detalhe.setdefault(cat, []).append({
            "desc": r["descricao"],
            "total": float(r["total"] or 0),
        })

    total_classif = sum(classif_totais.values())

    # Evolução mensal (linha)
    mensal = _db(f"""
        SELECT competencia,
               SUM(valor_budget)                                            AS total,
               COUNT(DISTINCT CASE WHEN descricao_verba = 'Salário'
                                   THEN matricula END)                       AS hc
        FROM budget_resultado
        WHERE {where}
        GROUP BY competencia
        ORDER BY competencia
    """, params)

    svg_mensal = _svg_line(
        [(m["competencia"], float(m["total"] or 0)) for m in mensal],
        [m["competencia"] for m in mensal],
    )

    # Por empresa (barras)
    por_empresa = _db(f"""
        SELECT empresa_nome,
               SUM(valor_budget)                                            AS total,
               COUNT(DISTINCT CASE WHEN descricao_verba = 'Salário'
                                   THEN matricula END)                       AS hc
        FROM budget_resultado
        WHERE {where}
        GROUP BY empresa_nome
        ORDER BY total DESC
    """, params)

    max_empresa = max((float(e["total"] or 0) for e in por_empresa), default=1)
    empresas_data = [
        {
            "nome": e["empresa_nome"],
            "total": float(e["total"] or 0),
            "pct": round(float(e["total"] or 0) / max(max_empresa, 1) * 100, 1),
            "hc": int(e["hc"] or 0),
            "per_capita": round(float(e["total"] or 0) / max(int(e["hc"] or 1), 1)),
        }
        for e in por_empresa
    ]
    empresas_pc = sorted(empresas_data, key=lambda x: -x["per_capita"])
    max_emp_total = max((e["total"] for e in empresas_data), default=1)
    max_pc_val = max((e["per_capita"] for e in empresas_pc), default=1)

    # Período label para o subtítulo
    comp_list = [m["competencia"] for m in mensal]
    if comp_list:
        periodo_label = f"{comp_list[0]} a {comp_list[-1]}" if len(comp_list) > 1 else comp_list[0]
    else:
        periodo_label = "—"

    # Percentual de cada categoria sobre o custo total empresa
    def _pct_te(v: float) -> float:
        return round(float(v) / max(total_empresa, 0.01) * 100, 2)

    pct_custo = {k: _pct_te(v) for k, v in classif_totais.items()}

    # Breakdown tree (classificação > rubricas, ordenado por total desc)
    ordem_cat = ["Salário", "Benefícios", "Provisão", "Adicionais", "Encargos", "PLR"]
    breakdown = []
    for cat in ordem_cat:
        t = classif_totais.get(cat, 0)
        if t == 0:
            continue
        detalhe = sorted(classif_detalhe.get(cat, []), key=lambda x: -x["total"])
        breakdown.append({
            "cat": cat,
            "emoji": _EMOJI.get(cat, ""),
            "total": t,
            "pct_do_total": round(t / max(total_classif, 1) * 100, 1),
            "itens": detalhe,
        })

    svg_per_capita = _svg_percapita(empresas_data)

    return templates.TemplateResponse(
        "indicadores/folha_custo_empresa.html",
        {
            "request": request,
            "todas_empresas": todas_empresas,
            "todas_comps": todas_comps,
            "empresa_sel": empresa,
            "comp_ini_sel": comp_ini,
            "comp_fim_sel": comp_fim,
            "total_empresa": total_empresa,
            "total_prov": total_prov,
            "total_fgts": total_fgts,
            "headcount": headcount,
            "classif_totais": classif_totais,
            "total_classif": total_classif,
            "svg_mensal": svg_mensal,
            "mensal": mensal,
            "empresas_data": empresas_data,
            "empresas_pc": empresas_pc,
            "max_emp_total": max_emp_total,
            "max_pc_val": max_pc_val,
            "breakdown": breakdown,
            "pct_custo": pct_custo,
            "periodo_label": periodo_label,
            "svg_per_capita": svg_per_capita,
            "brl": _brl,
        },
    )


# ═══════════════════════════════════════════════════════════════════════════
#  2. HOLERITE COLABORADOR
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/indicadores/folha-holerite")
def folha_holerite(
    request: Request,
    empresa: str = "",
    competencia: str = "",
    colaborador: str = "",
):
    todas_empresas, todas_comps = _opcoes()

    # Lista de colaboradores (filtrada por empresa/competência)
    colab_where = ["1=1"]
    colab_params: dict = {}
    if empresa:
        colab_where.append("fa.empresa_nome = :empresa")
        colab_params["empresa"] = empresa
    if competencia:
        colab_where.append("ff.competencia = :competencia")
        colab_params["competencia"] = competencia
    w_str = " AND ".join(colab_where)

    todos_colabs = [r["nome"] for r in _db(f"""
        SELECT DISTINCT ff.nome
        FROM folha_funcionarios ff
        JOIN folha_arquivos fa ON fa.id_arquivo = ff.id_arquivo
        WHERE {w_str}
        ORDER BY ff.nome
    """, colab_params)]

    func = None
    rubricas_p: list[dict] = []
    rubricas_d: list[dict] = []
    evolucao: list[dict] = []
    svg_evolucao = ""

    if colaborador:
        # dados do funcionário no período
        func_rows = _db(f"""
            SELECT ff.*, fa.empresa_nome
            FROM folha_funcionarios ff
            JOIN folha_arquivos fa ON fa.id_arquivo = ff.id_arquivo
            WHERE ff.nome = :nome
              AND (:empresa = '' OR fa.empresa_nome = :empresa)
              AND (:comp    = '' OR ff.competencia  = :comp)
            ORDER BY ff.competencia DESC
            LIMIT 1
        """, {"nome": colaborador, "empresa": empresa, "comp": competencia})

        if func_rows:
            func = func_rows[0]
            id_func = func["id_funcionario"]

            # rubricas do funcionário naquele mês
            rubs = _db("""
                SELECT fr.descricao, fr.tipo, fr.valor, fr.referencia
                FROM folha_rubricas fr
                WHERE fr.id_funcionario = :id_func
                ORDER BY fr.tipo, fr.valor DESC
            """, {"id_func": id_func})

            rubricas_p = [r for r in rubs if r["tipo"] == "P"]
            rubricas_d = [r for r in rubs if r["tipo"] == "D"]

            # evolução do salário (últimos 6 meses)
            evolucao = _db("""
                SELECT ff.competencia, ff.salario
                FROM folha_funcionarios ff
                JOIN folha_arquivos fa ON fa.id_arquivo = ff.id_arquivo
                WHERE ff.nome = :nome
                  AND (:empresa = '' OR fa.empresa_nome = :empresa)
                ORDER BY ff.competencia
                LIMIT 6
            """, {"nome": colaborador, "empresa": empresa})

            if evolucao:
                svg_evolucao = _svg_line(
                    [(e["competencia"], float(e["salario"] or 0)) for e in evolucao],
                    [e["competencia"] for e in evolucao],
                )

    # Classifica rubricas_p por categoria
    def _grupo_p(cat: str) -> list[dict]:
        return [r for r in rubricas_p if _classif(r["descricao"]) == cat]

    prov_salario    = _grupo_p("Salário")
    prov_adicionais = _grupo_p("Adicionais")
    prov_proventos  = prov_salario + prov_adicionais
    prov_beneficios = _grupo_p("Benefícios")
    prov_provisao   = _grupo_p("Provisão")
    prov_plr        = _grupo_p("PLR")

    total_salario           = sum(r["valor"] or 0 for r in prov_salario)
    total_adicionais        = sum(r["valor"] or 0 for r in prov_adicionais)
    total_proventos_classif = total_salario + total_adicionais
    total_beneficios        = sum(r["valor"] or 0 for r in prov_beneficios)
    total_provisao          = sum(r["valor"] or 0 for r in prov_provisao)
    total_plr               = sum(r["valor"] or 0 for r in prov_plr)
    total_descontos         = sum(r["valor"] or 0 for r in rubricas_d)
    fgts                    = float(func["valor_fgts"] or 0) if func else 0
    salario_base            = float(func["salario"] or 0) if func else 0
    total_custo             = total_proventos_classif + total_beneficios + total_provisao + total_plr + fgts
    liquido                 = float(func["liquido"] or 0) if func else 0

    # Ranking das categorias — separando Salário e Adicionais
    ranking = sorted([
        {"cat": "Salário",    "emoji": "💰", "total": total_salario},
        {"cat": "Benefícios", "emoji": "🎁", "total": total_beneficios},
        {"cat": "Provisão",   "emoji": "📦", "total": total_provisao},
        {"cat": "Encargos",   "emoji": "🏛️", "total": fgts},
        {"cat": "PLR",        "emoji": "🏆", "total": total_plr},
        {"cat": "Adicionais", "emoji": "⚡", "total": total_adicionais},
    ], key=lambda x: -x["total"])

    max_rank = max((r["total"] for r in ranking), default=1)
    for r in ranking:
        r["pct"] = round(r["total"] / max(max_rank, 1) * 100, 1)

    # Descontos identificados
    inss_emp = sum(r["valor"] or 0 for r in rubricas_d
                   if "I.N.S.S" in r["descricao"].upper() or
                      ("INSS" in r["descricao"].upper() and "EMPREGADOR" not in r["descricao"].upper()))
    irrf_emp = sum(r["valor"] or 0 for r in rubricas_d
                   if "IMPOSTO DE RENDA" in r["descricao"].upper() or
                      ("IRRF" in r["descricao"].upper() and "EMPREGADOR" not in r["descricao"].upper()))
    outros_desc = [r for r in rubricas_d
                   if "I.N.S.S" not in r["descricao"].upper()
                   and "INSS" not in r["descricao"].upper()
                   and "IMPOSTO DE RENDA" not in r["descricao"].upper()
                   and "IRRF" not in r["descricao"].upper()]

    return templates.TemplateResponse(
        "indicadores/folha_holerite.html",
        {
            "request": request,
            "todas_empresas": todas_empresas,
            "todas_comps": todas_comps,
            "todos_colabs": todos_colabs,
            "empresa_sel": empresa,
            "comp_sel": competencia,
            "colab_sel": colaborador,
            "func": func,
            "salario_base": salario_base,
            "total_custo": total_custo,
            "total_proventos_classif": total_proventos_classif,
            "total_beneficios": total_beneficios,
            "total_provisao": total_provisao,
            "total_plr": total_plr,
            "fgts": fgts,
            "total_descontos": total_descontos,
            "liquido": liquido,
            "prov_proventos": prov_proventos,
            "prov_beneficios": prov_beneficios,
            "prov_provisao": prov_provisao,
            "prov_plr": prov_plr,
            "rubricas_d": rubricas_d,
            "inss_emp": inss_emp,
            "irrf_emp": irrf_emp,
            "outros_desc": outros_desc,
            "ranking": ranking,
            "evolucao": evolucao,
            "svg_evolucao": svg_evolucao,
            "brl": _brl,
        },
    )
