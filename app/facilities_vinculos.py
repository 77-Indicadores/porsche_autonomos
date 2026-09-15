"""Reconecta complementos antigos, presos ao número da linha, ao chamado certo.

Até esta mudança o complemento (status, datas, custo) era guardado com o
número da linha da planilha. Quando uma linha era apagada, as de baixo subiam
e cada complemento passava a aparecer no chamado seguinte. A identidade do
chamado agora é estável, mas os complementos gravados antes continuam com o
número antigo — e parte deles já está deslocada.

Não dá para saber de memória qual linha foi apagada. Dá para descobrir pelos
dados: quando alguém complementa, o formulário vem preenchido com o local, a
categoria e a natureza do chamado, e a data de início não pode ser anterior à
abertura. Para cada complemento testamos em qual chamado ele se encaixa — o
da mesma linha, o de uma acima, duas acima... — e escolhemos o deslocamento
que mais concorda, com a restrição de que ele só cresce descendo a planilha
(apagar uma linha desloca todas as de baixo, nunca as de cima).

Nada é gravado sem o administrador ver a proposta e confirmar.
"""

from __future__ import annotations

import unicodedata
from datetime import datetime

DESLOCAMENTO_MAX = 8


def _norm(v) -> str:
    v = unicodedata.normalize("NFKD", str(v or "")).encode("ascii", "ignore").decode()
    return " ".join(v.lower().split())


def _data(v):
    if not v:
        return None
    if isinstance(v, datetime):
        return v.date()
    v = str(v).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(v[:19] if "%H" in fmt else v[:10], fmt).date()
        except ValueError:
            pass
    return None


def pontuar(comp: dict, t: dict) -> float:
    """Quanto o complemento concorda com o chamado. Negativo = impossível."""
    pts = 0.0
    und = _norm(comp.get("unidade_local"))
    if und:
        pts += 2 if und in (_norm(t.get("unit")), _norm(t.get("location"))) else -1
    area = _norm(comp.get("area_servico"))
    if area:
        if area == _norm(t.get("category")):
            pts += 2
        elif area == _norm(t.get("department")):
            pts += 1
    tipo = _norm(comp.get("tipo_atendimento"))
    if tipo:
        pts += 2 if tipo == _norm(t.get("maintenance_type")) else -1
    ini, aberto = _data(comp.get("data_inicio")), _data(t.get("created_at"))
    if ini and aberto:
        pts += 1 if ini >= aberto else -4   # começar antes de abrir não existe
    return pts


def propor(legados: dict[int, dict], chamados: dict[int, dict]) -> list[dict]:
    """legados: linha antiga -> complemento; chamados: linha atual -> chamado.

    Programação dinâmica sobre as linhas antigas em ordem, com deslocamento
    não decrescente. Mudar de deslocamento custa um pouco, para não pular por
    causa de um campo que alguém editou à mão.
    """
    linhas = sorted(legados)
    if not linhas:
        return []
    D = DESLOCAMENTO_MAX
    NEG = float("-inf")
    melhor = [[NEG] * (D + 1) for _ in linhas]
    veio = [[0] * (D + 1) for _ in linhas]

    def ganho(i, d):
        t = chamados.get(linhas[i] - d)
        return pontuar(legados[linhas[i]], t) if t else -6

    for d in range(D + 1):
        melhor[0][d] = ganho(0, d) - 0.5 * d
    for i in range(1, len(linhas)):
        for d in range(D + 1):
            ant = max(range(d + 1), key=lambda a: melhor[i - 1][a] - (0.5 * (d - a)))
            melhor[i][d] = melhor[i - 1][ant] - 0.5 * (d - ant) + ganho(i, d)
            veio[i][d] = ant
    d = max(range(D + 1), key=lambda x: melhor[-1][x])
    offs = [0] * len(linhas)
    for i in range(len(linhas) - 1, -1, -1):
        offs[i] = d
        d = veio[i][d]

    propostas = []
    usados: dict[int, int] = {}
    for i, r in enumerate(linhas):
        alvo = r - offs[i]
        t = chamados.get(alvo)
        p = {
            "linha_antiga": r, "deslocamento": offs[i], "linha_atual": alvo if t else None,
            "complemento": legados[r], "chamado": t,
            "pontos": pontuar(legados[r], t) if t else None,
        }
        if t is None:
            p["acao"] = "sem chamado"
        elif alvo in usados:
            # dois complementos caíram no mesmo chamado: um deles era do chamado
            # que foi apagado. Fica o que mais concorda com o chamado; empate
            # descarta o de baixo, que é onde o deslocamento mudou.
            outro = propostas[usados[alvo]]
            if (p["pontos"] or 0) > (outro["pontos"] or 0):
                outro["acao"] = "descartar"
                p["acao"] = "mover" if offs[i] else "manter"
                usados[alvo] = len(propostas)
            else:
                p["acao"] = "descartar"
        else:
            p["acao"] = "mover" if offs[i] else "manter"
            usados[alvo] = len(propostas)
        # encaixe que contradiz o chamado (local ou natureza diferentes, início
        # antes da abertura) não é aplicado: vai para revisão manual
        if p["acao"] in ("mover", "manter") and (p["pontos"] or 0) < 0:
            p["acao"] = "revisar"
            usados.pop(alvo, None)
        p["duvida"] = p["acao"] in ("mover", "manter") and (p["pontos"] or 0) < 2
        propostas.append(p)
    return propostas
