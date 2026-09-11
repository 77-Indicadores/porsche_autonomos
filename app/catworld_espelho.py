"""Espelho local das tabelas do Catworld.

Por que existe
--------------
Cada painel de indicador consultava o Catworld a cada requisição, e cada clique
em filtro repetia a consulta inteira. Medido em produção: ~260ms nas telas que
leem só o banco local contra 1.053ms (turnover), 1.102ms (headcount), 1.456ms
(horas extras) e 2.963ms na primeira carga. Trocar de empresa numa tela já
aberta custava 1.220ms — sem nada ter mudado na origem.

Some-se a isso que a origem cai: ao longo de um único dia o Catworld devolveu
503 de manhã e 500 à tarde, e com ele os cinco painéis ficaram em branco.

É o que o guia de performance do dash_adl prescreve:

    "Dashboards devem ler a camada presentation ou metrics, nunca depender
     diretamente de fonte externa lenta por padrão."
    "Materializar quando: (...) a fonte externa é instável ou lenta."

Como funciona
-------------
As linhas do Catworld são copiadas para `catworld_espelho`. Os painéis leem
SEMPRE do espelho — nunca da rede — então respondem em tempo de banco local e
continuam funcionando quando a origem está fora.

A atualização acontece fora do caminho da requisição: quando o espelho passa da
validade, a requisição devolve o que já tem e dispara a cópia numa thread. Só a
primeira vez, com o espelho ainda vazio, espera de fato — não há o que servir.

Cada tabela guarda quando foi sincronizada, para a tela poder dizer de quando é
o dado em vez de deixar o usuário supor que é de agora.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timedelta

from sqlalchemy import (Column, DateTime, Integer, MetaData, String, Table, Text,
                        delete, insert, select)

from app.database import engine

metadata_espelho = MetaData()

catworld_espelho = Table(
    "catworld_espelho",
    metadata_espelho,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("tabela", String(80), index=True),
    Column("ordem", Integer),
    # A linha vai como JSON de propósito: as tabelas do Catworld mudam de
    # colunas sem aviso, e uma cópia com colunas fixas quebraria na próxima
    # mudança. O formato entregue aos painéis é o mesmo de antes: lista de dict.
    Column("dados", Text),
)

catworld_espelho_status = Table(
    "catworld_espelho_status",
    metadata_espelho,
    Column("tabela", String(80), primary_key=True),
    Column("sincronizado_em", DateTime),
    Column("linhas", Integer),
    Column("duracao_ms", Integer),
    Column("erro", Text),
)

metadata_espelho.create_all(engine)


# Validade do espelho. Passado isso, a próxima visita dispara a cópia em
# segundo plano — quem pediu a página não espera por ela.
VALIDADE_MIN = int(os.getenv("CATWORLD_ESPELHO_MINUTOS", "15") or 15)

_em_andamento: set[str] = set()
_trava = threading.Lock()


def _agora() -> datetime:
    return datetime.now()


def status(tabela: str) -> dict | None:
    """Quando a tabela foi copiada pela última vez, e como foi."""
    try:
        with engine.connect() as cx:
            linha = cx.execute(
                select(catworld_espelho_status)
                .where(catworld_espelho_status.c.tabela == tabela)
            ).mappings().first()
        return dict(linha) if linha else None
    except Exception as exc:
        print(f"AVISO - não consegui ler o status do espelho ({tabela}): {exc}")
        return None


def sincronizado_em(tabela: str) -> datetime | None:
    st = status(tabela)
    return st.get("sincronizado_em") if st else None


def ler(tabela: str) -> list[dict]:
    """Linhas guardadas, na ordem em que vieram da origem."""
    try:
        with engine.connect() as cx:
            linhas = cx.execute(
                select(catworld_espelho.c.dados)
                .where(catworld_espelho.c.tabela == tabela)
                .order_by(catworld_espelho.c.ordem)
            ).all()
    except Exception as exc:
        print(f"AVISO - não consegui ler o espelho ({tabela}): {exc}")
        return []

    saida = []
    for (bruto,) in linhas:
        try:
            saida.append(json.loads(bruto))
        except Exception:
            continue
    return saida


def _gravar(tabela: str, linhas: list[dict], duracao_ms: int) -> None:
    """Troca o conteúdo da tabela espelhada por inteiro.

    Apagar e inserir na MESMA transação: se o processo morrer no meio, o
    espelho volta ao que era em vez de ficar pela metade, o que apareceria nos
    painéis como gente que sumiu.
    """
    agora = _agora()
    with engine.begin() as cx:
        cx.execute(delete(catworld_espelho).where(catworld_espelho.c.tabela == tabela))
        if linhas:
            # em blocos: um INSERT único com milhares de linhas estoura o
            # limite de parâmetros de alguns bancos
            registros = [{"tabela": tabela, "ordem": i,
                          "dados": json.dumps(linha, default=str, ensure_ascii=False)}
                         for i, linha in enumerate(linhas)]
            for ini in range(0, len(registros), 500):
                cx.execute(insert(catworld_espelho), registros[ini:ini + 500])

        cx.execute(delete(catworld_espelho_status)
                   .where(catworld_espelho_status.c.tabela == tabela))
        cx.execute(insert(catworld_espelho_status), {
            "tabela": tabela, "sincronizado_em": agora,
            "linhas": len(linhas), "duracao_ms": duracao_ms, "erro": None,
        })


def _registrar_erro(tabela: str, erro: str) -> None:
    """Guarda a falha sem tocar nas linhas: o espelho anterior continua valendo."""
    try:
        with engine.begin() as cx:
            st = cx.execute(
                select(catworld_espelho_status.c.sincronizado_em,
                       catworld_espelho_status.c.linhas)
                .where(catworld_espelho_status.c.tabela == tabela)
            ).first()
            cx.execute(delete(catworld_espelho_status)
                       .where(catworld_espelho_status.c.tabela == tabela))
            cx.execute(insert(catworld_espelho_status), {
                "tabela": tabela,
                "sincronizado_em": st[0] if st else None,
                "linhas": st[1] if st else 0,
                "duracao_ms": None,
                "erro": erro[:500],
            })
    except Exception as exc:
        print(f"AVISO - não consegui registrar a falha do espelho ({tabela}): {exc}")


def atualizar(tabela: str, buscar) -> dict:
    """Copia a tabela da origem para o espelho. Devolve o resultado."""
    inicio = _agora()
    try:
        linhas = buscar(tabela)
    except Exception as exc:
        _registrar_erro(tabela, f"{type(exc).__name__}: {exc}")
        return {"ok": False, "erro": str(exc), "linhas": 0}

    duracao = int((_agora() - inicio).total_seconds() * 1000)
    try:
        _gravar(tabela, linhas, duracao)
    except Exception as exc:
        _registrar_erro(tabela, f"ao gravar: {exc}")
        return {"ok": False, "erro": str(exc), "linhas": 0}
    return {"ok": True, "linhas": len(linhas), "duracao_ms": duracao}


def _atualizar_em_segundo_plano(tabela: str, buscar) -> None:
    """Dispara a cópia sem segurar a requisição.

    A trava evita que dez visitas simultâneas a um espelho vencido virem dez
    cópias concorrentes da mesma tabela.
    """
    with _trava:
        if tabela in _em_andamento:
            return
        _em_andamento.add(tabela)

    def tarefa():
        try:
            atualizar(tabela, buscar)
        finally:
            with _trava:
                _em_andamento.discard(tabela)

    threading.Thread(target=tarefa, daemon=True,
                     name=f"espelho-{tabela}").start()


def obter(tabela: str, buscar) -> list[dict]:
    """O que os painéis chamam: devolve as linhas, sempre do espelho.

    Espelho vazio é o único caso que espera a origem — não há o que entregar.
    Vencido, entrega o que tem e manda atualizar por trás.
    """
    st = status(tabela)
    tem_dado = bool(st and st.get("sincronizado_em"))

    if not tem_dado:
        atualizar(tabela, buscar)
        return ler(tabela)

    vencido = (_agora() - st["sincronizado_em"]) > timedelta(minutes=VALIDADE_MIN)
    if vencido:
        _atualizar_em_segundo_plano(tabela, buscar)
    return ler(tabela)


def tabelas_conhecidas() -> list[str]:
    """Tabelas que já foram espelhadas ao menos uma vez."""
    try:
        with engine.connect() as cx:
            return [r[0] for r in cx.execute(
                select(catworld_espelho_status.c.tabela)
                .order_by(catworld_espelho_status.c.tabela)).all()]
    except Exception:
        return []
