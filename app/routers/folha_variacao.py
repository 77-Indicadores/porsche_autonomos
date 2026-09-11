"""Indicador de variação de custo — gráfico de cascata.

O painel de custos mostra a série mensal, então dá para VER que o custo subiu
de R$ 1,19 milhão para R$ 2,11 milhões. O que ele não responde é a pergunta
seguinte, que é a que interessa: subiu por quê, e quanto cada verba contribuiu.

A cascata responde isso. Começa na base (mês anterior ou média dos últimos
três), soma e subtrai a contribuição de cada verba, e fecha no mês analisado.
A altura de cada degrau é a contribuição — quem puxou para cima aparece grande,
não importa se a verba é grande ou pequena no total.

Por que MÉDIA DOS 3 MESES e não só o mês anterior: mês a mês qualquer
sazonalidade vira alarme. Comparar agosto com a média de maio, junho e julho
separa "este mês foi diferente" de "o mês passado é que foi atípico".
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from app.routers.folha_custo import _brl, _classif, _db
from app.template_config import templates
from app.ui_filtros import CSS_FILTROS, JS_FILTROS, caixa_multi, lista_sel

router = APIRouter(tags=["indicadores"])

BASES = [("anterior", "Mês anterior"), ("media3", "Média dos 3 meses anteriores")]
DETALHES = [("verba", "Verba"), ("grupo", "Grupo")]
QUANTIDADES = ["5", "8", "10", "15", "Todas"]


def _competencias() -> list[str]:
    """Competências disponíveis, da mais antiga para a mais nova."""
    return [r["competencia"] for r in _db(
        "SELECT DISTINCT competencia FROM budget_resultado "
        "WHERE COALESCE(competencia,'') <> '' ORDER BY competencia")]


def _ordenar(comps: list[str]) -> list[str]:
    """Ordena MM/AAAA por tempo, não por texto.

    Em ordem alfabética "01/2026" vem antes de "12/2025", e a média dos três
    meses anteriores pegaria meses errados sem ninguém perceber.
    """
    def chave(c: str) -> tuple:
        try:
            mes, ano = c.split("/")
            return (int(ano), int(mes))
        except Exception:
            return (0, 0)
    return sorted(comps, key=chave)


def _valores(competencia: str, empresas: list[str], por: str) -> dict[str, float]:
    """Custo por verba (ou grupo) de uma competência."""
    sql = ("SELECT descricao_verba AS verba, SUM(COALESCE(valor_budget,0)) AS total "
           "FROM budget_resultado WHERE competencia = :c")
    params: dict = {"c": competencia}
    if empresas:
        marcas = ", ".join(f":e{i}" for i in range(len(empresas)))
        sql += f" AND empresa_nome IN ({marcas})"
        for i, e in enumerate(empresas):
            params[f"e{i}"] = e
    sql += " GROUP BY descricao_verba"

    saida: dict[str, float] = {}
    for r in _db(sql, params):
        nome = (r["verba"] or "Sem descrição").strip()
        if por == "grupo":
            nome = _classif(nome)
        saida[nome] = saida.get(nome, 0.0) + float(r["total"] or 0)
    return saida


def _media(competencias: list[str], empresas: list[str], por: str) -> dict[str, float]:
    """Média por verba entre as competências informadas.

    Divide sempre pela quantidade de MESES do recorte, não pelo número de meses
    em que a verba apareceu: uma verba que existiu em um mês só tem média menor
    mesmo — é isso que a torna excepcional quando aparece de novo.
    """
    if not competencias:
        return {}
    soma: dict[str, float] = {}
    for c in competencias:
        for verba, valor in _valores(c, empresas, por).items():
            soma[verba] = soma.get(verba, 0.0) + valor
    return {k: v / len(competencias) for k, v in soma.items()}


def _svg_cascata(base_valor: float, passos: list[dict], atual: float,
                 rot_base: str, rot_atual: str) -> str:
    """Cascata: base, contribuições, total.

    As barras intermediárias flutuam — começam onde a anterior parou —, que é o
    que mostra o efeito acumulado. Base e total ficam apoiados no eixo, porque
    são valores absolutos e não contribuições.
    """
    if not passos and not base_valor and not atual:
        return "<p style='color:#69717D;padding:24px'>Sem dados para o período escolhido.</p>"

    larg_barra, espaco, topo, base_y = 64, 22, 40, 300
    n = len(passos) + 2
    largura = max(760, n * (larg_barra + espaco) + espaco)
    altura = base_y + 110

    # a escala considera todo o caminho percorrido, não só o início e o fim:
    # um degrau pode subir acima do total e voltar
    corrente = base_valor
    extremos = [base_valor, atual]
    for p in passos:
        corrente += p["delta"]
        extremos.append(corrente)

    # O eixo NÃO começa em zero, de propósito. Com base de R$ 1,2 milhão e
    # degraus de R$ 20 mil, partir do zero transforma cada degrau numa fatia de
    # dois pixels — o gráfico fica bonito e ilegível, e ele existe justamente
    # para comparar os degraus entre si. A escala cobre o caminho percorrido
    # pela cascata, com folga; os valores vão escritos em cima de cada barra,
    # então não há como ler a altura errado.
    alto, baixo = max(extremos), min(extremos)
    margem = (alto - baixo) * 0.25 or (alto * 0.05) or 1.0
    teto = alto + margem
    piso = max(baixo - margem, 0.0)
    faixa = (teto - piso) or 1.0

    def y(valor: float) -> float:
        valor = min(max(valor, piso), teto)
        return topo + (teto - valor) / faixa * (base_y - topo)

    partes = [f'<svg viewBox="0 0 {largura} {altura}" xmlns="http://www.w3.org/2000/svg"'
              f' style="width:100%;height:auto;display:block">']

    # linha da base, para comparar cada degrau com o ponto de partida
    partes.append(f'<line x1="0" y1="{y(base_valor):.1f}" x2="{largura}"'
                  f' y2="{y(base_valor):.1f}" stroke="#d9d9de"'
                  f' stroke-width="1" stroke-dasharray="4 4"/>')

    def barra(i: int, de: float, ate: float, cor: str, rotulo: str,
              valor_txt: str, sub: str = "") -> None:
        x = espaco + i * (larg_barra + espaco)
        y0, y1 = y(max(de, ate)), y(min(de, ate))
        alt = max(y1 - y0, 2)
        partes.append(f'<rect x="{x}" y="{y0:.1f}" width="{larg_barra}"'
                      f' height="{alt:.1f}" fill="{cor}" rx="3"/>')
        partes.append(f'<text x="{x + larg_barra/2:.0f}" y="{y0 - 8:.1f}"'
                      f' text-anchor="middle" font-size="11" font-weight="700"'
                      f' fill="#252525" font-family="Inter,system-ui,sans-serif">{valor_txt}</text>')
        # rótulo em duas linhas: nome de verba é longo e cortado não serve
        palavras, linha, linhas = rotulo.split(), "", []
        for w in palavras:
            if len(linha + " " + w) > 13 and linha:
                linhas.append(linha); linha = w
            else:
                linha = (linha + " " + w).strip()
        if linha:
            linhas.append(linha)
        for j, texto in enumerate(linhas[:2]):
            partes.append(f'<text x="{x + larg_barra/2:.0f}" y="{base_y + 18 + j*12}"'
                          f' text-anchor="middle" font-size="10" fill="#69717D"'
                          f' font-family="Inter,system-ui,sans-serif">{texto}</text>')
        if sub:
            partes.append(f'<text x="{x + larg_barra/2:.0f}"'
                          f' y="{base_y + 18 + min(len(linhas),2)*12}"'
                          f' text-anchor="middle" font-size="10" fill="#9aa0ab"'
                          f' font-family="Inter,system-ui,sans-serif">{sub}</text>')

    barra(0, piso, base_valor, "#69717D", rot_base, _brl(base_valor))
    corrente = base_valor
    for i, p in enumerate(passos, start=1):
        # vermelho só para o que aumenta o custo — é o que pede ação
        cor = "#D50032" if p["delta"] > 0 else "#078647"
        barra(i, corrente, corrente + p["delta"], cor, p["nome"],
              ("+" if p["delta"] > 0 else "") + _brl(p["delta"]), p.get("sub", ""))
        corrente += p["delta"]
    barra(len(passos) + 1, piso, atual, "#0B0B0C", rot_atual, _brl(atual))

    # Marca de eixo cortado. Sem ela a barra da base (43px) parece cinco vezes
    # menor que a do total (217px), quando a diferença real é de 17% — o corte
    # que tornou os degraus legíveis distorce as duas barras absolutas. O
    # zigue-zague na base é a convenção para avisar que o eixo não começa em
    # zero, e o número escrito em cada barra continua sendo a verdade.
    if piso > 0:
        dentes = []
        x = 0
        while x < largura:
            dentes.append(f"{x},{base_y + 4} {x + 6},{base_y - 3}")
            x += 12
        partes.append(f'<polyline points="{" ".join(dentes)}" fill="none"'
                      f' stroke="#c9ccd2" stroke-width="1.5"/>')
        partes.append(f'<text x="{largura - 4}" y="{base_y + 16}" text-anchor="end"'
                      f' font-size="9" fill="#9aa0ab"'
                      f' font-family="Inter,system-ui,sans-serif">eixo cortado</text>')

    partes.append("</svg>")
    return "".join(partes)


_CSS = """<style>
.vr-wrap{font-family:Inter,system-ui,-apple-system,sans-serif;color:#252525}
.vr-topo{display:flex;gap:16px;flex-wrap:wrap;margin-bottom:24px}
.vr-kpi{background:#fff;border-radius:10px;box-shadow:0 1px 4px rgba(0,0,0,.07);
  padding:16px 24px;flex:1;min-width:200px}
.vr-kpi-lbl{font-size:11px;font-weight:700;letter-spacing:.04em;
  text-transform:uppercase;color:#69717D;margin-bottom:8px}
.vr-kpi-val{font-size:28px;font-weight:800;line-height:1.1;font-variant-numeric:tabular-nums}
.vr-kpi-sub{font-size:12px;color:#69717D;margin-top:4px}
.vr-sobe{color:#D50032}
.vr-desce{color:#078647}
.vr-painel{background:#fff;border-radius:10px;box-shadow:0 1px 4px rgba(0,0,0,.07);
  padding:24px;margin-bottom:24px}
.vr-painel-head{font-size:14px;font-weight:800;margin-bottom:4px}
.vr-painel-sub{font-size:12px;color:#69717D;margin-bottom:24px}
.vr-rolagem{overflow-x:auto;min-width:0}
.vr-tab{width:100%;border-collapse:collapse;font-size:13px}
.vr-tab th{text-align:right;padding:8px 12px;font-size:11px;font-weight:700;
  letter-spacing:.04em;text-transform:uppercase;color:#69717D;
  border-bottom:1px solid #e6e6e9;white-space:nowrap}
.vr-tab th:first-child,.vr-tab td:first-child{text-align:left}
.vr-tab td{padding:12px;border-bottom:1px solid #f2f2f4}
.vr-tab tbody tr:hover{background:#fafafa}
.vr-nome{font-weight:600;color:#0B0B0C}
.vr-num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.vr-aviso{background:#fff;border-left:4px solid #C69D4C;border-radius:8px;
  box-shadow:0 1px 4px rgba(0,0,0,.07);padding:16px 24px;margin-bottom:24px;
  font-size:13px;line-height:1.5}
</style>"""


@router.get("/indicadores/folha-variacao")
def folha_variacao(request: Request,
                   competencia: str = "",
                   base: str = "anterior",
                   por: str = "verba",
                   quantidade: str = "10",
                   empresa: list[str] = Query(default=[])):
    comps = _ordenar(_competencias())
    empresas_todas = [r["empresa_nome"] for r in _db(
        "SELECT DISTINCT empresa_nome FROM budget_resultado "
        "WHERE COALESCE(empresa_nome,'') <> '' ORDER BY empresa_nome")]
    empresa_sel = lista_sel(empresa)

    if competencia not in comps:
        competencia = comps[-1] if comps else ""

    if base not in dict(BASES):
        base = "anterior"
    if por not in dict(DETALHES):
        por = "verba"

    idx = comps.index(competencia) if competencia in comps else -1
    anteriores = comps[:idx] if idx > 0 else []
    if base == "media3":
        usados = anteriores[-3:]
    else:
        usados = anteriores[-1:]

    atual_por_verba = _valores(competencia, empresa_sel, por) if competencia else {}
    base_por_verba = _media(usados, empresa_sel, por)

    atual_total = sum(atual_por_verba.values())
    base_total = sum(base_por_verba.values())
    delta_total = atual_total - base_total
    pct = (delta_total / base_total * 100) if base_total else 0.0

    # uma linha por verba que existe em qualquer um dos dois lados: a verba que
    # SUMIU é tão explicativa quanto a que apareceu
    nomes = set(atual_por_verba) | set(base_por_verba)
    linhas = []
    for nome in nomes:
        de = base_por_verba.get(nome, 0.0)
        para = atual_por_verba.get(nome, 0.0)
        linhas.append({
            "nome": nome, "de": de, "para": para, "delta": para - de,
            "pct": ((para - de) / de * 100) if de else None,
        })
    linhas.sort(key=lambda x: -abs(x["delta"]))

    try:
        limite = int(quantidade)
    except ValueError:
        limite = len(linhas)

    # O que fica de fora vira um degrau "Demais verbas" em vez de sumir — sem
    # isso a cascata não fecha no total do mês e o gráfico mente.
    principais = [l for l in linhas if abs(l["delta"]) > 0.005][:limite]
    resto = [l for l in linhas if l not in principais]
    delta_resto = sum(l["delta"] for l in resto)

    passos = [{"nome": l["nome"], "delta": l["delta"],
               "sub": f"{l['pct']:+.0f}%" if l["pct"] is not None else "novo"}
              for l in principais]
    if abs(delta_resto) > 0.005:
        passos.append({"nome": f"Demais ({len(resto)})", "delta": delta_resto, "sub": ""})

    rot_base = ("Média " + " · ".join(usados)) if base == "media3" and usados else (
        usados[0] if usados else "Sem base")
    svg = _svg_cascata(base_total, passos, atual_total, rot_base, competencia)

    def _opts(valores, atual_v):
        return "".join(
            f"<option value='{v}'{' selected' if str(v) == str(atual_v) else ''}>{r}</option>"
            for v, r in valores)

    filtros = (
        f"{CSS_FILTROS}"
        f'<form method="get" action="/indicadores/folha-variacao"'
        f' class="ind-filtros" id="indFiltros">'
        f'<div class="ind-filtro"><label>Competência</label>'
        f'<select name="competencia" onchange="this.form.submit()">'
        f'{_opts([(c, c) for c in reversed(comps)], competencia)}</select></div>'
        f'<div class="ind-filtro"><label>Comparar com</label>'
        f'<select name="base" onchange="this.form.submit()">'
        f'{_opts(BASES, base)}</select></div>'
        f'<div class="ind-filtro"><label>Detalhar por</label>'
        f'<select name="por" onchange="this.form.submit()">'
        f'{_opts(DETALHES, por)}</select></div>'
        f'<div class="ind-filtro"><label>Quantidade</label>'
        f'<select name="quantidade" onchange="this.form.submit()">'
        f'{_opts([(q, q) for q in QUANTIDADES], quantidade)}</select></div>'
        + caixa_multi("empresa", "Empresa",
                      [(e, e) for e in empresas_todas], empresa_sel, "Todas")
        + "</form>" + JS_FILTROS)

    aviso = ""
    if not usados:
        aviso = ('<div class="vr-aviso">Não há mês anterior para comparar — '
                 'esta é a competência mais antiga da base.</div>')
    elif base == "media3" and len(usados) < 3:
        aviso = (f'<div class="vr-aviso">A base usa {len(usados)} '
                 f'mês(es) — {", ".join(usados)} —, porque não há três meses '
                 f'anteriores na base.</div>')

    cor = "vr-sobe" if delta_total > 0 else "vr-desce"
    sinal = "+" if delta_total > 0 else ""
    rotulo_por = dict(DETALHES)[por].lower()

    def _linha_tab(l: dict) -> str:
        # Os pedaços saem da f-string de propósito: f-string dentro de f-string
        # com aspas do mesmo tipo só é válida no Python 3.12+, e produção roda
        # 3.11 — o módulo inteiro deixava de importar, e com ele a aplicação.
        classe = "vr-sobe" if l["delta"] > 0 else "vr-desce"
        sinal = "+" if l["delta"] > 0 else ""
        pct = "novo" if l["pct"] is None else "{:+.1f}%".format(l["pct"])
        return ('<tr><td class="vr-nome">{}</td>'
                '<td class="vr-num">{}</td>'
                '<td class="vr-num">{}</td>'
                '<td class="vr-num {}">{}{}</td>'
                '<td class="vr-num">{}</td></tr>').format(
            l["nome"], _brl(l["de"]), _brl(l["para"]),
            classe, sinal, _brl(l["delta"]), pct)

    tabela = "".join(_linha_tab(l) for l in linhas if abs(l["delta"]) > 0.005)

    dash = f"""{filtros}<div class="vr-wrap">{_CSS}
{aviso}
<div class="vr-topo">
  <div class="vr-kpi">
    <div class="vr-kpi-lbl">Base de comparação</div>
    <div class="vr-kpi-val">{_brl(base_total)}</div>
    <div class="vr-kpi-sub">{rot_base}</div>
  </div>
  <div class="vr-kpi">
    <div class="vr-kpi-lbl">{competencia or "—"}</div>
    <div class="vr-kpi-val">{_brl(atual_total)}</div>
    <div class="vr-kpi-sub">Custo do mês</div>
  </div>
  <div class="vr-kpi">
    <div class="vr-kpi-lbl">Variação</div>
    <div class="vr-kpi-val {cor}">{sinal}{_brl(delta_total)}</div>
    <div class="vr-kpi-sub {cor}">{sinal}{pct:.1f}% sobre a base</div>
  </div>
</div>

<div class="vr-painel">
  <div class="vr-painel-head">Do que veio a variação</div>
  <div class="vr-painel-sub">
    Cada degrau é quanto a {rotulo_por} contribuiu para sair de
    {_brl(base_total)} e chegar a {_brl(atual_total)}.
    Vermelho aumenta o custo, verde reduz.
    O eixo começa acima de zero para os degraus ficarem legíveis — os valores
    estão escritos em cada barra.
  </div>
  <div class="vr-rolagem">{svg}</div>
</div>

<div class="vr-painel">
  <div class="vr-painel-head">Detalhe por {rotulo_por}</div>
  <div class="vr-painel-sub">Ordenado pelo tamanho da variação</div>
  <div class="vr-rolagem">
    <table class="vr-tab">
      <thead><tr>
        <th>{dict(DETALHES)[por]}</th><th>Base</th><th>{competencia or "Mês"}</th>
        <th>Variação</th><th>%</th>
      </tr></thead>
      <tbody>{tabela or '<tr><td colspan="5" style="text-align:center;padding:24px;color:#69717D">Sem variação no período.</td></tr>'}</tbody>
    </table>
  </div>
</div>
</div>"""

    return templates.TemplateResponse("indicadores/folha_variacao.html", {
        "request": request,
        "dash_html": dash,
        "erro": None,
    })
