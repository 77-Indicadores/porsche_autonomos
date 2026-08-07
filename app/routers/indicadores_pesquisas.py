"""Indicador de Pesquisas — satisfação, avaliação e permanência.

As pesquisas convivem com duas escalas (0–10 nos formulários de piloto e 1–5
no resto). Para comparar grupos, cada nota vira um índice 0–100 conforme a
escala da própria pergunta; as médias brutas continuam disponíveis por grupo.
"""
from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.template_config import templates

router = APIRouter(tags=["indicadores_pesquisas"])

CORES = ["#15946c", "#2878d0", "#e59a12", "#d71920", "#7259be", "#0f7c8a", "#8a6f2d"]

ORDEM_ESCALA = ["Excelente", "Bom", "Regular", "Ruim", "Péssimo"]
COR_ESCALA = {
    "Excelente": "#15946c",
    "Bom": "#5bbf8a",
    "Regular": "#e59a12",
    "Ruim": "#e2683c",
    "Péssimo": "#d71920",
}


def _rosca(dados: list[tuple], tamanho: int = 190, espessura: int = 30,
           cores: dict | None = None) -> str:
    """SVG de rosca. dados = [(rótulo, valor), ...]."""
    total = sum(v for _, v in dados)
    if not total:
        return "<p style='color:#9ca3af;font-size:12px'>Sem dados no filtro atual.</p>"

    r = (tamanho - espessura) / 2
    cx = cy = tamanho / 2
    circ = 2 * 3.141592653589793 * r

    partes, offset = [], 0.0
    for i, (rot, val) in enumerate(dados):
        frac = val / total
        cor = (cores or {}).get(rot) or CORES[i % len(CORES)]
        partes.append(
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{cor}" '
            f'stroke-width="{espessura}" '
            f'stroke-dasharray="{circ * frac:.2f} {circ:.2f}" '
            f'stroke-dashoffset="{-offset:.2f}" '
            f'transform="rotate(-90 {cx} {cy})"><title>{rot}: {val}</title></circle>'
        )
        offset += circ * frac

    legenda = "".join(
        f'<div style="display:flex;align-items:center;gap:6px;font-size:11px;margin-bottom:3px">'
        f'<i style="width:10px;height:10px;border-radius:3px;background:'
        f'{(cores or {}).get(rot) or CORES[i % len(CORES)]};display:inline-block"></i>'
        f'<span style="flex:1;color:#4b5563">{rot}</span>'
        f'<b style="color:#111827">{val}</b>'
        f'<span style="color:#9ca3af">{val / total * 100:.0f}%</span></div>'
        for i, (rot, val) in enumerate(dados)
    )

    return f"""
<div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap">
  <svg viewBox="0 0 {tamanho} {tamanho}" style="width:{tamanho}px;height:{tamanho}px;flex-shrink:0">
    {''.join(partes)}
    <text x="{cx}" y="{cy - 4}" text-anchor="middle" font-size="26" font-weight="700"
          fill="#111827">{total}</text>
    <text x="{cx}" y="{cy + 14}" text-anchor="middle" font-size="10" fill="#9ca3af">respostas</text>
  </svg>
  <div style="min-width:170px;flex:1">{legenda}</div>
</div>"""


def _barras(dados: list[tuple], sufixo: str = "") -> str:
    """Barras horizontais. dados = [(rótulo, valor 0–100, texto)]."""
    if not dados:
        return "<p style='color:#9ca3af;font-size:12px'>Sem dados no filtro atual.</p>"
    linhas = []
    for rot, pct, txt in dados:
        cor = "#15946c" if pct >= 80 else ("#e59a12" if pct >= 60 else "#d71920")
        linhas.append(f"""
<div style="display:grid;grid-template-columns:170px 1fr 74px;align-items:center;gap:10px;margin-bottom:7px">
  <div style="font-size:12px;color:#374151;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{rot}</div>
  <div style="background:#eef0f4;border-radius:999px;height:9px;overflow:hidden">
    <div style="width:{pct:.1f}%;height:100%;background:{cor};border-radius:999px"></div>
  </div>
  <div style="font-size:12px;font-weight:700;color:#111827;text-align:right">{txt}{sufixo}</div>
</div>""")
    return "".join(linhas)


def _escala_por_pergunta(rows) -> dict:
    """Máximo observado por pergunta, para saber se é escala 5 ou 10."""
    maximos: dict = defaultdict(float)
    for r in rows:
        if r["nota_num"] is not None:
            k = r["pergunta_original"] or ""
            maximos[k] = max(maximos[k], float(r["nota_num"]))
    return {k: (10.0 if v > 5 else 5.0) for k, v in maximos.items()}


@router.get("/indicadores/pesquisas")
def indicador_pesquisas(request: Request, db: Session = Depends(get_db)):
    erro = None
    dash_html = ""
    try:
        dash_html = _build(db, request)
    except Exception as exc:
        import traceback
        traceback.print_exc()
        erro = f"Erro ao montar o indicador: {exc}"

    return templates.TemplateResponse("indicadores/pesquisas.html", {
        "request": request, "dash_html": dash_html, "erro": erro,
    })


def _build(db: Session, request: Request) -> str:
    f_etapa = request.query_params.get("etapa", "")
    f_tipo = request.query_params.get("tipo", "")
    f_cat = request.query_params.get("categoria", "")

    where, params = ["1=1"], {}
    if f_etapa:
        where.append("p.id_etapa = :et")
        params["et"] = int(f_etapa)
    if f_tipo:
        where.append("p.tipo_pesquisa = :tp")
        params["tp"] = f_tipo
    if f_cat:
        where.append("p.categoria_forms = :ct")
        params["ct"] = f_cat
    w = " AND ".join(where)

    rows = db.execute(text(f"""
        SELECT p.tipo_pesquisa, p.grupo_pergunta, p.subgrupo_pergunta,
               p.pergunta_original, p.nota_num, p.resposta_padronizada,
               p.manter_trocar, p.categoria_forms, p.id_etapa,
               COALESCE(e.nome_etapa, 'Sem etapa definida') AS etapa
        FROM pesquisa_respostas p
        LEFT JOIN dim_etapas e ON e.id_etapa = p.id_etapa
        WHERE {w}
    """), params).mappings().all()

    if not rows:
        return ("<p style='padding:24px;color:#6b7280'>Nenhuma resposta importada "
                "ainda. Importe as planilhas em <a href='/pesquisas'>Pesquisas</a>.</p>")

    escalas = _escala_por_pergunta(rows)

    def indice(r):
        """Nota em 0–100, conforme a escala da pergunta."""
        if r["nota_num"] is None:
            return None
        base = escalas.get(r["pergunta_original"] or "", 5.0)
        return min(float(r["nota_num"]) / base * 100, 100.0)

    # ── KPIs ──
    indices = [i for i in (indice(r) for r in rows) if i is not None]
    satisfacao = sum(indices) / len(indices) if indices else 0

    manter = sum(1 for r in rows if r["manter_trocar"] == "Manter")
    trocar = sum(1 for r in rows if r["manter_trocar"] == "Trocar")
    pct_manter = manter / (manter + trocar) * 100 if (manter + trocar) else 0

    escala_cont = defaultdict(int)
    for r in rows:
        if r["resposta_padronizada"] in COR_ESCALA:
            escala_cont[r["resposta_padronizada"]] += 1
    total_escala = sum(escala_cont.values())
    positivas = escala_cont["Excelente"] + escala_cont["Bom"]
    pct_positivas = positivas / total_escala * 100 if total_escala else 0

    respondentes = len({(r["tipo_pesquisa"], r["etapa"], r["categoria_forms"]) for r in rows})

    kpis = [
        ("Respostas", f"{len(rows):,}".replace(",", "."), "registros padronizados", "#111827"),
        ("Satisfação geral", f"{satisfacao:.1f}", "índice 0–100, escalas normalizadas", "#15946c"),
        ("Avaliações positivas", f"{pct_positivas:.1f}%", "Excelente ou Bom", "#2878d0"),
        ("Permanência", f"{pct_manter:.1f}%", f"{manter} manter · {trocar} trocar", "#7259be"),
    ]
    kpis_html = "".join(f"""
<article style="background:#fff;border:1px solid #e3e7ee;border-radius:12px;padding:14px 16px">
  <div style="font-size:11px;font-weight:700;color:#6f7886;text-transform:uppercase;letter-spacing:.05em">{t}</div>
  <div style="font-size:26px;font-weight:800;color:{c};line-height:1.25">{v}</div>
  <div style="font-size:11px;color:#9ca3af">{s}</div>
</article>""" for t, v, s, c in kpis)

    # ── roscas ──
    dados_escala = [(k, escala_cont[k]) for k in ORDEM_ESCALA if escala_cont.get(k)]
    rosca_escala = _rosca(dados_escala, cores=COR_ESCALA)

    rosca_perm = _rosca(
        [(k, v) for k, v in [("Manter", manter), ("Trocar", trocar)] if v],
        cores={"Manter": "#15946c", "Trocar": "#d71920"},
    )

    por_tipo = defaultdict(int)
    for r in rows:
        por_tipo[r["tipo_pesquisa"]] += 1
    from app.routers.pesquisas import TIPOS_CURTO
    rosca_tipo = _rosca(sorted(
        ((TIPOS_CURTO.get(k, k), v) for k, v in por_tipo.items()),
        key=lambda x: -x[1],
    ))

    # ── média por grupo ──
    por_grupo = defaultdict(list)
    for r in rows:
        i = indice(r)
        if i is not None and r["grupo_pergunta"] and r["grupo_pergunta"] != "Comentário":
            por_grupo[r["grupo_pergunta"]].append(i)
    grupos = sorted(
        ((g, sum(v) / len(v), len(v)) for g, v in por_grupo.items() if len(v) >= 5),
        key=lambda x: -x[1],
    )
    barras_grupo = _barras([(g, m, f"{m:.0f}") for g, m, _ in grupos])

    # ── itens mais bem e pior avaliados ──
    por_item = defaultdict(list)
    for r in rows:
        i = indice(r)
        if i is not None and r["subgrupo_pergunta"]:
            rot = f"{r['grupo_pergunta']} · {r['subgrupo_pergunta']}"
            por_item[rot].append(i)
    itens = sorted(
        ((k, sum(v) / len(v), len(v)) for k, v in por_item.items() if len(v) >= 5),
        key=lambda x: -x[1],
    )
    melhores = _barras([(k, m, f"{m:.0f}") for k, m, _ in itens[:6]])
    piores = _barras([(k, m, f"{m:.0f}") for k, m, _ in itens[-6:][::-1]])

    # ── evolução por etapa ──
    por_etapa = defaultdict(list)
    for r in rows:
        i = indice(r)
        if i is not None:
            por_etapa[r["etapa"]].append(i)
    etapas_ord = sorted((e, sum(v) / len(v), len(v)) for e, v in por_etapa.items())
    barras_etapa = _barras([(e, m, f"{m:.0f}") for e, m, _ in etapas_ord])

    # ── filtros ──
    etapas_op = db.execute(text(
        "SELECT DISTINCT p.id_etapa, e.nome_etapa FROM pesquisa_respostas p "
        "JOIN dim_etapas e ON e.id_etapa = p.id_etapa ORDER BY e.nome_etapa"
    )).fetchall()
    cats = [r[0] for r in db.execute(text(
        "SELECT DISTINCT categoria_forms FROM pesquisa_respostas "
        "WHERE categoria_forms IS NOT NULL AND categoria_forms <> '' ORDER BY 1"
    )).fetchall()]

    def _opts(itens_op, sel, todos="Todas"):
        out = f"<option value=''>{todos}</option>"
        for val, rot in itens_op:
            s = " selected" if str(val) == str(sel) else ""
            out += f"<option value='{val}'{s}>{rot}</option>"
        return out

    filtros = f"""
<form method="get" action="/indicadores/pesquisas"
      style="display:flex;gap:12px;flex-wrap:wrap;align-items:end;background:#fff;
             border:1px solid #e3e7ee;border-radius:12px;padding:12px 16px;margin-bottom:14px">
  <div><label style="display:block;font-size:11px;font-weight:700;color:#6f7886;
       text-transform:uppercase;letter-spacing:.05em;margin-bottom:3px">Etapa</label>
    <select name="etapa" onchange="this.form.submit()" style="border:1px solid #e3e7ee;border-radius:7px;padding:6px 10px;font-size:13px;font-weight:600;min-width:180px">
      {_opts([(e[0], e[1]) for e in etapas_op], f_etapa)}
    </select></div>
  <div><label style="display:block;font-size:11px;font-weight:700;color:#6f7886;
       text-transform:uppercase;letter-spacing:.05em;margin-bottom:3px">Pesquisa</label>
    <select name="tipo" onchange="this.form.submit()" style="border:1px solid #e3e7ee;border-radius:7px;padding:6px 10px;font-size:13px;font-weight:600;min-width:180px">
      {_opts(list(TIPOS_CURTO.items()), f_tipo, "Todas")}
    </select></div>
  <div><label style="display:block;font-size:11px;font-weight:700;color:#6f7886;
       text-transform:uppercase;letter-spacing:.05em;margin-bottom:3px">Categoria</label>
    <select name="categoria" onchange="this.form.submit()" style="border:1px solid #e3e7ee;border-radius:7px;padding:6px 10px;font-size:13px;font-weight:600;min-width:160px">
      {_opts([(c, c) for c in cats], f_cat)}
    </select></div>
  <a href="/indicadores/pesquisas" style="font-size:12px;color:#6b7280;text-decoration:none;padding-bottom:7px">✕ Limpar</a>
</form>"""

    def card(titulo, sub, corpo):
        return f"""
<article style="background:#fff;border:1px solid #e3e7ee;border-radius:12px;padding:16px">
  <h3 style="margin:0;font-size:14px;font-weight:700;color:#18202c">{titulo}</h3>
  <p style="margin:2px 0 12px;font-size:11px;color:#9ca3af">{sub}</p>
  {corpo}
</article>"""

    return f"""
<div style="font-family:Inter,ui-sans-serif,system-ui,sans-serif">
{filtros}

<section style="display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px;margin-bottom:14px">
  {kpis_html}
</section>

<section style="display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:12px;margin-bottom:14px">
  {card("Distribuição das avaliações", "Escala qualitativa das pesquisas", rosca_escala)}
  {card("Manter ou trocar", "Decisão registrada sobre o profissional", rosca_perm)}
  {card("Respostas por pesquisa", "Volume de cada formulário", rosca_tipo)}
</section>

<section style="display:grid;grid-template-columns:repeat(auto-fit,minmax(380px,1fr));gap:12px;margin-bottom:14px">
  {card("Índice por grupo", "0–100, escalas 1–5 e 0–10 normalizadas", barras_grupo)}
  {card("Índice por etapa", "Evolução ao longo da temporada", barras_etapa)}
</section>

<section style="display:grid;grid-template-columns:repeat(auto-fit,minmax(380px,1fr));gap:12px">
  {card("Itens mais bem avaliados", "Mínimo de 5 respostas", melhores)}
  {card("Itens com menor nota", "Onde focar a ação", piores)}
</section>
</div>"""
