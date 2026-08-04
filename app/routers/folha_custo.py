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


def _foto_map() -> dict[str, str]:
    """Carrega mapa matricula→foto_url da tabela dho_empregados (se existir)."""
    try:
        rows = _db("SELECT matricula, foto_url FROM dho_empregados WHERE foto_url IS NOT NULL AND foto_url != ''")
        return {str(r["matricula"]): r["foto_url"] for r in rows if r["matricula"]}
    except Exception:
        return {}


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
        f'{_brl(p[1], 0)}</text>'
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


def _dependentes_map(competencia: str = "") -> dict[str, int]:
    """Dependentes por matrícula.

    A fonte é o `nd` da folha importada — o mesmo campo que o cálculo do budget
    usa. O valor editado em Níveis de Cargo tem prioridade, mas só quando existe:
    a tela grava `budget_cargos` apenas quando alguém a salva, e sem esse
    fallback o holerite mostrava zero para todo mundo.
    """
    try:
        rows = _db("""
            SELECT ff.matricula AS matricula,
                   MAX(COALESCE(NULLIF(bc.dependentes, 0), ff.nd, 0)) AS dep
            FROM folha_funcionarios ff
            LEFT JOIN budget_cargos bc
                   ON bc.matricula = ff.matricula
                  AND bc.competencia = ff.competencia
            WHERE (:comp = '' OR ff.competencia = :comp)
              AND ff.matricula IS NOT NULL AND ff.matricula <> ''
            GROUP BY ff.matricula
        """, {"comp": competencia or ""})
        return {str(r["matricula"]): int(r["dep"] or 0) for r in rows}
    except Exception as exc:
        print(f"AVISO - dependentes: {exc}")
        return {}


def _deptos() -> list[str]:
    """Departamentos disponíveis, vindos do cadastro de centros de custo."""
    try:
        return [r["nome"] for r in _db(
            "SELECT DISTINCT nome FROM folha_centros_custo "
            "WHERE COALESCE(status, 'Ativo') = 'Ativo' ORDER BY nome"
        )]
    except Exception as exc:
        print(f"AVISO - lista de departamentos: {exc}")
        return []


def _norm_empresa(s: str) -> str:
    """Só letras e dígitos, em maiúsculas — para comparar razões sociais."""
    return "".join(ch for ch in (s or "").upper() if ch.isalnum())


def _mesma_empresa(a: str, b: str) -> bool:
    """A folha grava a razão social truncada e sem pontuação; compara por prefixo."""
    na, nb = _norm_empresa(a), _norm_empresa(b)
    if not na or not nb:
        return False
    return na.startswith(nb) or nb.startswith(na)


def _cond_depto(departamento: str, empresa: str = "") -> tuple[str, dict]:
    """Condição SQL que restringe centro_custo aos códigos do departamento."""
    if not departamento:
        return "", {}
    try:
        rows = _db(
            "SELECT empresa, codigo FROM folha_centros_custo "
            "WHERE nome = :n AND COALESCE(status, 'Ativo') = 'Ativo'",
            {"n": departamento},
        )
    except Exception as exc:
        print(f"AVISO - códigos do departamento: {exc}")
        return "", {}

    if empresa:
        rows = [r for r in rows if _mesma_empresa(empresa, r["empresa"])]
    codigos = sorted({r["codigo"] for r in rows})

    if not codigos:
        return "1=0", {}
    marcas = ", ".join(f":dcc{i}" for i in range(len(codigos)))
    return f"centro_custo IN ({marcas})", {f"dcc{i}": c for i, c in enumerate(codigos)}


def _where(empresa: str, comp_ini: str, comp_fim: str, prefix: str = "",
           departamento: str = "") -> tuple[str, dict]:
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
    cond_d, p_d = _cond_depto(departamento, empresa)
    if cond_d:
        conds.append(cond_d)
        p.update(p_d)
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
    departamento: str = "",
):
    todas_empresas, todas_comps = _opcoes()
    todos_deptos = _deptos()

    where, params = _where(empresa, comp_ini, comp_fim, departamento=departamento)

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
            "todos_deptos": todos_deptos,
            "empresa_sel": empresa,
            "comp_ini_sel": comp_ini,
            "comp_fim_sel": comp_fim,
            "depto_sel": departamento,
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
    departamento: str = "",
):
    todas_empresas, todas_comps = _opcoes()
    todos_deptos = _deptos()

    # Sempre força uma competência selecionada — padrão = a mais recente
    if not competencia and todas_comps:
        competencia = todas_comps[-1]

    # Lista de colaboradores do budget (filtrada por empresa/competência)
    colab_where = ["1=1"]
    colab_params: dict = {}
    if empresa:
        colab_where.append("empresa_nome = :empresa")
        colab_params["empresa"] = empresa
    if competencia:
        colab_where.append("competencia = :comp")
        colab_params["comp"] = competencia
    _cd, _pd = _cond_depto(departamento, empresa)
    if _cd:
        colab_where.append(_cd)
        colab_params.update(_pd)
    w_str = " AND ".join(colab_where)

    todos_colabs = [r["nome"] for r in _db(f"""
        SELECT DISTINCT nome_empregado AS nome
        FROM budget_resultado
        WHERE {w_str}
        ORDER BY nome_empregado
    """, colab_params)]

    func = None
    verbas: list[dict] = []
    rubricas_d: list[dict] = []
    evolucao: list[dict] = []
    svg_evolucao = ""

    if colaborador:
        # Verbas do budget para o colaborador/período
        verbas = _db("""
            SELECT descricao_verba AS descricao,
                   SUM(valor_budget) AS valor,
                   MIN(cargo_nome)   AS cargo,
                   MIN(cargo_grupo)  AS cargo_grupo,
                   MIN(empresa_nome) AS empresa_nome,
                   MIN(competencia)  AS competencia,
                   MIN(matricula)    AS matricula
            FROM budget_resultado
            WHERE nome_empregado = :nome
              AND (:empresa = '' OR empresa_nome = :empresa)
              AND (:comp    = '' OR competencia  = :comp)
            GROUP BY descricao_verba
            ORDER BY valor DESC
        """, {"nome": colaborador, "empresa": empresa, "comp": competencia or ""})

        if verbas:
            first   = verbas[0]
            mat     = first["matricula"]
            cargo   = (first["cargo"] or "").upper()
            eh_est  = "ESTAGIARIO" in cargo or "ESTAGIARIA" in cargo

            dependentes = _dependentes_map(competencia).get(str(mat), 0)

            # Admissão da folha real
            adm = _db("""
                SELECT MIN(ff.data_admissao) AS data_admissao
                FROM folha_funcionarios ff
                JOIN folha_arquivos fa ON fa.id_arquivo = ff.id_arquivo
                WHERE ff.nome = :nome
                  AND (:empresa = '' OR fa.empresa_nome = :empresa)
            """, {"nome": colaborador, "empresa": empresa})

            # Total bruto (Salário + Adicionais do budget)
            total_bruto = sum(float(v["valor"] or 0) for v in verbas
                              if _classif(v["descricao"]) in ("Salário", "Adicionais"))

            # INSS calculado pela tabela progressiva
            def _inss(base: float) -> float:
                if eh_est:
                    return 0.0
                if base <= 1412.00:     return base * 0.075
                if base <= 2666.68:     return 105.90  + (base - 1412.00) * 0.09
                if base <= 4000.03:     return 218.82  + (base - 2666.68) * 0.12
                if base <= 7786.02:     return 378.82  + (base - 4000.03) * 0.14
                return 908.85

            # IRRF calculado pela tabela progressiva
            def _irrf(bruto: float, inss: float, dep: int) -> float:
                base_ir = (bruto if eh_est else bruto - inss) - dep * 189.59
                if base_ir <= 2259.20:  return 0.0
                if base_ir <= 2826.65:  return base_ir * 0.075  - 169.44
                if base_ir <= 3751.05:  return base_ir * 0.15   - 381.44
                if base_ir <= 4664.68:  return base_ir * 0.225  - 662.77
                return base_ir * 0.275 - 896.00

            inss_val = _inss(total_bruto)
            irrf_val = _irrf(total_bruto, inss_val, dependentes)
            total_desc = max(inss_val + irrf_val, 0.0)

            rubricas_d = []
            if inss_val > 0:
                rubricas_d.append({"descricao": "INSS Empregado", "valor": round(inss_val, 2)})
            if irrf_val > 0:
                rubricas_d.append({"descricao": "IRRF",           "valor": round(irrf_val, 2)})

            func = {
                "nome":            colaborador,
                "empresa_nome":    first["empresa_nome"],
                "cargo":           first["cargo"],
                "cargo_grupo":     first["cargo_grupo"],
                "dependentes":     dependentes,
                "matricula":       mat,
                "competencia":     first["competencia"],
                "data_admissao":   adm[0]["data_admissao"] if adm else None,
                "total_proventos": total_bruto,
                "total_descontos": total_desc,
                "foto_url":        _foto_map().get(str(mat or "")),
            }

        # Evolução do salário base (meses disponíveis no budget)
        evolucao = _db("""
            SELECT competencia, SUM(valor_budget) AS salario
            FROM budget_resultado
            WHERE nome_empregado = :nome
              AND (:empresa = '' OR empresa_nome = :empresa)
              AND descricao_verba = 'Salário'
            GROUP BY competencia
            ORDER BY competencia
        """, {"nome": colaborador, "empresa": empresa})

        if evolucao:
            svg_evolucao = _svg_line(
                [(e["competencia"], float(e["salario"] or 0)) for e in evolucao],
                [e["competencia"] for e in evolucao],
            )

    # Classifica verbas do budget; Rescisório separado da Provisão
    _RESCISORIO = {"Provisão Aviso Prévio", "Multa do FGTS"}

    def _grupo(cat: str) -> list[dict]:
        return [v for v in verbas
                if _classif(v["descricao"]) == cat and v["descricao"] not in _RESCISORIO]

    prov_salario    = _grupo("Salário")
    prov_adicionais = _grupo("Adicionais")
    prov_proventos  = prov_salario + prov_adicionais
    prov_beneficios = _grupo("Benefícios")
    prov_provisao   = _grupo("Provisão")
    prov_plr        = _grupo("PLR")
    prov_encargos   = _grupo("Encargos")
    prov_rescisorio = [v for v in verbas if v["descricao"] in _RESCISORIO]

    total_salario    = sum(float(r["valor"] or 0) for r in prov_salario)
    total_adicionais = sum(float(r["valor"] or 0) for r in prov_adicionais)
    total_proventos  = total_salario + total_adicionais
    total_beneficios = sum(float(r["valor"] or 0) for r in prov_beneficios)
    total_provisao   = sum(float(r["valor"] or 0) for r in prov_provisao)
    total_plr        = sum(float(r["valor"] or 0) for r in prov_plr)
    total_encargos   = sum(float(r["valor"] or 0) for r in prov_encargos)
    total_rescisorio = sum(float(r["valor"] or 0) for r in prov_rescisorio)
    total_desc_val   = sum(float(r["valor"] or 0) for r in rubricas_d)
    salario_base     = total_salario
    liquido          = total_proventos - total_desc_val
    total_custo      = total_proventos + total_beneficios + total_provisao + total_plr + total_encargos + total_rescisorio
    fator_global     = round(total_custo / max(salario_base, 1), 2)

    ranking = sorted([
        {"cat": "Salário",    "emoji": "💰", "total": total_salario},
        {"cat": "Benefícios", "emoji": "🎁", "total": total_beneficios},
        {"cat": "Provisão",   "emoji": "📦", "total": total_provisao + total_rescisorio},
        {"cat": "Encargos",   "emoji": "🏛️", "total": total_encargos},
        {"cat": "PLR",        "emoji": "🏆", "total": total_plr},
        {"cat": "Adicionais", "emoji": "⚡", "total": total_adicionais},
    ], key=lambda x: -x["total"])
    max_rank = max((r["total"] for r in ranking), default=1)
    for r in ranking:
        r["pct"] = round(r["total"] / max(max_rank, 1) * 100, 1)

    return templates.TemplateResponse(
        "indicadores/folha_holerite.html",
        {
            "request":          request,
            "todas_empresas":   todas_empresas,
            "todas_comps":      todas_comps,
            "todos_deptos":     todos_deptos,
            "todos_colabs":     todos_colabs,
            "empresa_sel":      empresa,
            "comp_sel":         competencia,
            "depto_sel":        departamento,
            "colab_sel":        colaborador,
            "func":             func,
            "salario_base":     salario_base,
            "total_custo":      total_custo,
            "total_beneficios": total_beneficios,
            "total_provisao":   total_provisao,
            "total_encargos":   total_encargos,
            "total_rescisorio": total_rescisorio,
            "total_plr":        total_plr,
            "fgts":             total_encargos,
            "liquido":          liquido,
            "fator_global":     fator_global,
            "prov_proventos":   prov_proventos,
            "prov_beneficios":  prov_beneficios,
            "prov_provisao":    prov_provisao,
            "prov_encargos":    prov_encargos,
            "prov_rescisorio":  prov_rescisorio,
            "prov_plr":         prov_plr,
            "rubricas_d":       rubricas_d,
            "ranking":          ranking,
            "svg_evolucao":     svg_evolucao,
            "brl":              _brl,
        },
    )


# ─── Holerite · Lista ────────────────────────────────────────────────────────

def _calc_inss(base: float, eh_est: bool) -> float:
    if eh_est:               return 0.0
    if base <= 1412.00:      return base * 0.075
    if base <= 2666.68:      return 105.90 + (base - 1412.00) * 0.09
    if base <= 4000.03:      return 218.82 + (base - 2666.68) * 0.12
    if base <= 7786.02:      return 378.82 + (base - 4000.03) * 0.14
    return 908.85


def _calc_irrf(bruto: float, inss: float, dep: int, eh_est: bool) -> float:
    base_ir = (bruto if eh_est else bruto - inss) - dep * 189.59
    if base_ir <= 2259.20:   return 0.0
    if base_ir <= 2826.65:   return base_ir * 0.075 - 169.44
    if base_ir <= 3751.05:   return base_ir * 0.15  - 381.44
    if base_ir <= 4664.68:   return base_ir * 0.225 - 662.77
    return base_ir * 0.275 - 896.00


@router.get("/indicadores/folha-lista")
def folha_lista(
    request: Request,
    empresa: str = "",
    competencia: str = "",
    departamento: str = "",
):
    from collections import defaultdict

    todas_empresas, todas_comps = _opcoes()
    todos_deptos = _deptos()

    if not competencia and todas_comps:
        competencia = todas_comps[-1]

    _cd_lista, _pd_lista = _cond_depto(departamento, empresa)
    _and_dep = f" AND {_cd_lista}" if _cd_lista else ""

    verbas_todas = _db(f"""
        SELECT
            nome_empregado,
            descricao_verba          AS descricao,
            SUM(valor_budget)        AS valor,
            MIN(cargo_nome)          AS cargo,
            MIN(cargo_grupo)         AS cargo_grupo,
            MIN(matricula)           AS matricula
        FROM budget_resultado
        WHERE (:empresa = '' OR empresa_nome = :empresa)
          AND (:comp    = '' OR competencia  = :comp){_and_dep}
        GROUP BY nome_empregado, descricao_verba
        ORDER BY nome_empregado, valor DESC
    """, {"empresa": empresa, "comp": competencia, **_pd_lista})

    dep_map = _dependentes_map(competencia)

    _RESCISORIO_L = {"Provisão Aviso Prévio", "Multa do FGTS"}

    colabs: dict = defaultdict(list)
    for v in verbas_todas:
        colabs[v["nome_empregado"]].append(v)

    funcionarios = []
    for nome, verbas in sorted(colabs.items()):
        first     = verbas[0]
        mat       = first["matricula"]
        cargo     = first["cargo"] or ""
        eh_est    = "ESTAGIARIO" in cargo.upper() or "ESTAGIARIA" in cargo.upper()
        dep       = dep_map.get(mat, 0)

        prov_v  = [v for v in verbas if _classif(v["descricao"]) in ("Salário", "Adicionais") and v["descricao"] not in _RESCISORIO_L]
        benef_v = [v for v in verbas if _classif(v["descricao"]) == "Benefícios"]
        prsn_v  = [v for v in verbas if _classif(v["descricao"]) in ("Provisão", "Encargos") and v["descricao"] not in _RESCISORIO_L]
        plr_v   = [v for v in verbas if _classif(v["descricao"]) == "PLR"]
        resc_v  = [v for v in verbas if v["descricao"] in _RESCISORIO_L]

        tp   = sum(float(v["valor"] or 0) for v in prov_v)
        tb   = sum(float(v["valor"] or 0) for v in benef_v)
        tpr  = sum(float(v["valor"] or 0) for v in prsn_v)
        tplr = sum(float(v["valor"] or 0) for v in plr_v)
        tr   = sum(float(v["valor"] or 0) for v in resc_v)

        inss  = round(_calc_inss(tp, eh_est), 2)
        irrf  = round(_calc_irrf(tp, inss, dep, eh_est), 2)
        desc  = inss + irrf
        liq   = tp - desc
        pacote = liq + tb + tpr + tplr + tr

        funcionarios.append({
            "nome":      nome,
            "cargo":     cargo,
            "matricula": mat,
            "eh_est":    eh_est,
            "dep":       dep,
            "tp":        tp,
            "inss":      inss,
            "irrf":      irrf,
            "desc":      desc,
            "liq":       liq,
            "tb":        tb,
            "tpr":       tpr,
            "tplr":      tplr,
            "tr":        tr,
            "pacote":    pacote,
            "prov_v":    prov_v,
            "benef_v":   benef_v,
            "prsn_v":    prsn_v,
            "plr_v":     plr_v,
            "resc_v":    resc_v,
        })

    fotos = _foto_map()
    for f in funcionarios:
        f["foto_url"] = fotos.get(str(f["matricula"] or ""))

    total_pacote = sum(f["pacote"] for f in funcionarios)

    return templates.TemplateResponse(
        "indicadores/folha_lista.html",
        {
            "request":        request,
            "todas_empresas": todas_empresas,
            "todas_comps":    todas_comps,
            "todos_deptos":   todos_deptos,
            "empresa_sel":    empresa,
            "comp_sel":       competencia,
            "depto_sel":      departamento,
            "funcionarios":   funcionarios,
            "total_pacote":   total_pacote,
            "brl":            _brl,
        },
    )


# ─── Simulação de Aumento ────────────────────────────────────────────────────

@router.get("/indicadores/folha-simulacao")
def folha_simulacao(
    request: Request,
    empresa: str = "",
    competencia: str = "",
    colaborador: str = "",
    aumento: float = 0.0,
    departamento: str = "",
):
    todas_empresas, todas_comps = _opcoes()
    todos_deptos = _deptos()

    if not competencia and todas_comps:
        competencia = todas_comps[-1]

    colab_params: dict = {}
    colab_where = ["1=1"]
    if empresa:
        colab_where.append("empresa_nome = :empresa")
        colab_params["empresa"] = empresa
    if competencia:
        colab_where.append("competencia = :comp")
        colab_params["comp"] = competencia
    _cd, _pd = _cond_depto(departamento, empresa)
    if _cd:
        colab_where.append(_cd)
        colab_params.update(_pd)
    w_str = " AND ".join(colab_where)

    todos_colabs = [r["nome"] for r in _db(f"""
        SELECT DISTINCT nome_empregado AS nome
        FROM budget_resultado
        WHERE {w_str}
        ORDER BY nome_empregado
    """, colab_params)]

    atual = None
    simulado = None

    _RESCISORIO = {"Provisão Aviso Prévio", "Multa do FGTS"}

    if colaborador:
        verbas = _db("""
            SELECT descricao_verba AS descricao,
                   SUM(valor_budget) AS valor,
                   MIN(cargo_nome)   AS cargo,
                   MIN(empresa_nome) AS empresa_nome,
                   MIN(competencia)  AS competencia,
                   MIN(matricula)    AS matricula
            FROM budget_resultado
            WHERE nome_empregado = :nome
              AND (:empresa = '' OR empresa_nome = :empresa)
              AND (:comp    = '' OR competencia  = :comp)
            GROUP BY descricao_verba
            ORDER BY valor DESC
        """, {"nome": colaborador, "empresa": empresa, "comp": competencia or ""})

        if verbas:
            first  = verbas[0]
            mat    = first["matricula"]
            cargo  = (first["cargo"] or "").upper()
            eh_est = "ESTAGIARIO" in cargo or "ESTAGIARIA" in cargo

            dep = _dependentes_map(competencia).get(str(mat), 0)

            def _grupos(verbas_list, fator=1.0):
                prov_v  = [v for v in verbas_list if _classif(v["descricao"]) in ("Salário", "Adicionais") and v["descricao"] not in _RESCISORIO]
                benef_v = [v for v in verbas_list if _classif(v["descricao"]) == "Benefícios"]
                prsn_v  = [v for v in verbas_list if _classif(v["descricao"]) in ("Provisão", "Encargos") and v["descricao"] not in _RESCISORIO]
                plr_v   = [v for v in verbas_list if _classif(v["descricao"]) == "PLR"]
                resc_v  = [v for v in verbas_list if v["descricao"] in _RESCISORIO]

                tp   = sum(float(v["valor"] or 0) for v in prov_v)  * fator
                tb   = sum(float(v["valor"] or 0) for v in benef_v)          # benefícios: fixo
                tpr  = sum(float(v["valor"] or 0) for v in prsn_v)  * fator
                tplr = sum(float(v["valor"] or 0) for v in plr_v)   * fator
                tr   = sum(float(v["valor"] or 0) for v in resc_v)  * fator

                inss = round(_calc_inss(tp, eh_est), 2)
                irrf = round(_calc_irrf(tp, inss, dep, eh_est), 2)
                desc = inss + irrf
                liq  = tp - desc
                pacote = liq + tb + tpr + tplr + tr
                salario = sum(float(v["valor"] or 0) for v in prov_v if v["descricao"] == "Salário") * fator

                return {
                    "nome": colaborador,
                    "cargo": first["cargo"],
                    "empresa": first["empresa_nome"],
                    "competencia": first["competencia"],
                    "matricula": mat,
                    "dep": dep,
                    "eh_est": eh_est,
                    "prov_v":  [{"descricao": v["descricao"], "valor": float(v["valor"] or 0) * fator} for v in prov_v],
                    "benef_v": [{"descricao": v["descricao"], "valor": float(v["valor"] or 0)}          for v in benef_v],
                    "prsn_v":  [{"descricao": v["descricao"], "valor": float(v["valor"] or 0) * fator} for v in prsn_v],
                    "plr_v":   [{"descricao": v["descricao"], "valor": float(v["valor"] or 0) * fator} for v in plr_v],
                    "resc_v":  [{"descricao": v["descricao"], "valor": float(v["valor"] or 0) * fator} for v in resc_v],
                    "tp": tp, "tb": tb, "tpr": tpr, "tplr": tplr, "tr": tr,
                    "inss": inss, "irrf": irrf, "desc": desc,
                    "liq": liq, "pacote": pacote, "salario": salario,
                }

            fator = 1.0 + aumento / 100.0
            atual    = _grupos(verbas, fator=1.0)
            simulado = _grupos(verbas, fator=fator)

    return templates.TemplateResponse(
        "indicadores/folha_simulacao.html",
        {
            "request":        request,
            "todas_empresas": todas_empresas,
            "todas_comps":    todas_comps,
            "todos_deptos":   todos_deptos,
            "todos_colabs":   todos_colabs,
            "empresa_sel":    empresa,
            "comp_sel":       competencia,
            "depto_sel":      departamento,
            "colab_sel":      colaborador,
            "aumento":        aumento,
            "atual":          atual,
            "simulado":       simulado,
            "brl":            _brl,
        },
    )


# ─── Custo por Colaborador (Total Rewards Premium) ───────────────────────────

_CAT_ORDER = ["Salário", "Adicionais", "Encargos", "Benefícios", "Provisão", "PLR"]
_CAT_EMOJI = {
    "Salário":    "💰",
    "Adicionais": "⚡",
    "Encargos":   "🏛️",
    "Benefícios": "🎁",
    "Provisão":   "📦",
    "PLR":        "🏆",
}


@router.get("/indicadores/folha-custo-colaborador")
def custo_colaborador(
    request: Request,
    empresa: str = "",
    competencia: str = "",
    colaborador: str = "",
    departamento: str = "",
):
    todas_empresas, todas_comps = _opcoes()
    todos_deptos = _deptos()

    if not competencia and todas_comps:
        competencia = todas_comps[-1]

    colab_params: dict = {}
    colab_where = ["1=1"]
    if empresa:
        colab_where.append("empresa_nome = :empresa")
        colab_params["empresa"] = empresa
    if competencia:
        colab_where.append("competencia = :comp")
        colab_params["comp"] = competencia
    _cd, _pd = _cond_depto(departamento, empresa)
    if _cd:
        colab_where.append(_cd)
        colab_params.update(_pd)
    w_str = " AND ".join(colab_where)

    todos_colabs = [r["nome"] for r in _db(f"""
        SELECT DISTINCT nome_empregado AS nome
        FROM budget_resultado
        WHERE {w_str}
        ORDER BY nome_empregado
    """, colab_params)]

    func = None
    categorias = []

    if colaborador:
        verbas = _db("""
            SELECT descricao_verba AS descricao,
                   SUM(valor_budget) AS valor,
                   MIN(cargo_nome)   AS cargo,
                   MIN(empresa_nome) AS empresa_nome,
                   MIN(competencia)  AS competencia,
                   MIN(matricula)    AS matricula
            FROM budget_resultado
            WHERE nome_empregado = :nome
              AND (:empresa = '' OR empresa_nome = :empresa)
              AND (:comp    = '' OR competencia  = :comp)
            GROUP BY descricao_verba
            ORDER BY valor DESC
        """, {"nome": colaborador, "empresa": empresa, "comp": competencia or ""})

        if verbas:
            first = verbas[0]
            total = sum(float(v["valor"] or 0) for v in verbas)
            sal   = sum(float(v["valor"] or 0) for v in verbas if _classif(v["descricao"]) == "Salário")
            ben   = sum(float(v["valor"] or 0) for v in verbas if _classif(v["descricao"]) == "Benefícios")
            prov  = sum(float(v["valor"] or 0) for v in verbas if _classif(v["descricao"]) == "Provisão")
            outros = total - sal - ben - prov

            def _pct(v): return round(v / max(total, 1) * 100, 2)

            # Agrupamento por categoria, ordenado
            cat_map: dict[str, list] = {c: [] for c in _CAT_ORDER}
            for v in verbas:
                cat = _classif(v["descricao"])
                if cat in cat_map:
                    cat_map[cat].append({"descricao": v["descricao"], "valor": float(v["valor"] or 0)})

            for cat in _CAT_ORDER:
                itens = cat_map[cat]
                if not itens:
                    continue
                subtotal = sum(i["valor"] for i in itens)
                categorias.append({
                    "cat":      cat,
                    "emoji":    _CAT_EMOJI.get(cat, ""),
                    "itens":    itens,
                    "subtotal": subtotal,
                    "pct_sal":  round(subtotal / max(sal if cat == "Salário" else total, 1) * 100, 1),
                    "pct_tot":  round(subtotal / max(total, 1) * 100, 1),
                })

            func = {
                "nome":        colaborador,
                "cargo":       first["cargo"],
                "empresa":     first["empresa_nome"],
                "matricula":   first["matricula"],
                "competencia": first["competencia"],
                "total":       total,
                "sal":         sal,
                "ben":         ben,
                "prov":        prov,
                "outros":      outros,
                "pct_sal":     _pct(sal),
                "pct_ben":     _pct(ben),
                "pct_prov":    _pct(prov),
                "pct_out":     _pct(outros),
            }

    return templates.TemplateResponse(
        "indicadores/folha_custo_colaborador.html",
        {
            "request":        request,
            "todas_empresas": todas_empresas,
            "todas_comps":    todas_comps,
            "todos_deptos":   todos_deptos,
            "todos_colabs":   todos_colabs,
            "empresa_sel":    empresa,
            "comp_sel":       competencia,
            "depto_sel":      departamento,
            "colab_sel":      colaborador,
            "func":           func,
            "categorias":     categorias,
            "brl":            _brl,
        },
    )
