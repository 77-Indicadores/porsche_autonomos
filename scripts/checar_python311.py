"""Verifica se o código roda no Python de produção (3.11).

Por que existe
--------------
O ambiente de desenvolvimento aqui é Python 3.13; produção roda 3.11
(`FROM python:3.11-slim` no Dockerfile). Duas vezes um código que importava sem
erro localmente derrubou produção:

1. aspas simples dentro de f-string delimitada por aspas simples — o router de
   indicadores parou de registrar e todas as telas de indicador deram 404;
2. f-string dentro de f-string com o mesmo tipo de aspas — a aplicação INTEIRA
   deixou de subir, com 503 em todas as rotas.

As duas são válidas a partir do 3.12 (PEP 701) e são SyntaxError no 3.11.

Por que ast.parse não basta
---------------------------
    ast.parse(codigo, feature_version=(3, 11))

parece resolver e não resolve: o 3.12 mudou a TOKENIZAÇÃO das f-strings, e
`feature_version` não volta o tokenizador atrás — o parser do 3.13 aceita a
sintaxe nova independentemente do valor passado (conferido). Continua rodando
aqui porque cobre outras mudanças de gramática; o que ele não cobre é
justamente o que quebrou.

Por que tokenize e não varredura própria
----------------------------------------
A primeira versão deste arquivo varria o texto caractere a caractere e errava:
acusou 38 trechos que rodam em produção há meses — f-strings de aspas triplas,
onde uma aspa avulsa é válida, e `f'... filename="{x}"'`, de aspas alternadas.
Verificador que acusa o que está certo ensina a ser ignorado, e aí não serve
para nada. O tokenizador do próprio Python sabe onde cada f-string começa e
termina.

Uso
---
    python scripts/checar_python311.py

Sai com código 1 se achar algo, para poder entrar num hook ou na CI.
"""

from __future__ import annotations

import ast
import io
import pathlib
import sys
import token
import tokenize

RAIZ = pathlib.Path(__file__).resolve().parent.parent
ALVO = (3, 11)

TRIPLOS = ('"""', "'''")


def _delimitador(texto: str) -> str:
    """Delimitador de um literal, já sem o prefixo (f, r, rb...)."""
    corpo = texto.lstrip("rRbBuUfF")
    return corpo[:3] if corpo[:3] in TRIPLOS else corpo[:1]


def _problemas_em_fstrings(fonte: str) -> list[tuple[int, str]]:
    """Colisão de delimitador ou barra invertida dentro de f-string.

    No 3.12+ o tokenizador emite FSTRING_START / FSTRING_MIDDLE / FSTRING_END, e
    o que aparece entre START e END são os tokens da expressão — exatamente o
    que precisa ser examinado.
    """
    achados: list[tuple[int, str]] = []
    inicio = getattr(token, "FSTRING_START", None)
    encerra = getattr(token, "FSTRING_END", None)
    if inicio is None:          # Python < 3.12 já tokeniza como o 3.11
        return achados

    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(fonte).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return achados

    pilha: list[str] = []
    for tok in tokens:
        if tok.type == inicio:
            delim = _delimitador(tok.string)
            # f-string dentro de f-string só quebra se as aspas colidirem:
            # f'{f"{x}"}' é válido no 3.11.
            if pilha and pilha[-1] == delim:
                achados.append((
                    tok.start[0],
                    "f-string dentro de f-string com o mesmo delimitador "
                    + repr(delim)))
            pilha.append(delim)
            continue

        if tok.type == encerra:
            if pilha:
                pilha.pop()
            continue

        if not pilha:
            continue

        # Compara com TODOS os delimitadores abertos, não só o mais interno:
        # em f'{f"{l['pct']}"}' a aspa simples colide com a f-string de FORA,
        # e olhar só a de dentro deixava passar exatamente o caso que derrubou
        # a aplicação.
        if tok.type == token.STRING:
            usado = _delimitador(tok.string)
            if usado in pilha:
                achados.append((
                    tok.start[0],
                    "string com o delimitador " + repr(usado)
                    + " dentro de f-string delimitada igual: " + tok.string[:40]))
            elif "\\" in tok.string:
                achados.append((
                    tok.start[0],
                    "barra invertida dentro da f-string: " + tok.string[:40]))

    return achados


def main() -> int:
    falhas = 0
    for arquivo in sorted(RAIZ.joinpath("app").rglob("*.py")):
        fonte = arquivo.read_text(encoding="utf-8-sig")
        rel = arquivo.relative_to(RAIZ)

        try:
            ast.parse(fonte, filename=str(rel), feature_version=ALVO)
        except SyntaxError as exc:
            falhas += 1
            print(f"{rel}:{exc.lineno}: {exc.msg}")

        for linha, motivo in _problemas_em_fstrings(fonte):
            falhas += 1
            print(f"{rel}:{linha}: {motivo}")
            print("    (válido no 3.12+, SyntaxError no 3.11 — "
                  "tire o valor de dentro da f-string)")

    alvo = ".".join(str(x) for x in ALVO)
    if falhas:
        print(f"\n{falhas} problema(s) que quebram no Python {alvo}.")
        return 1
    print(f"OK — nada que quebre no Python {alvo}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
