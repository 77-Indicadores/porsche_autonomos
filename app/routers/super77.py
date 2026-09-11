"""Área técnica: estado das integrações e do espelho de dados.

Os painéis passaram a ler de um espelho local do Catworld, atualizado por uma
thread em segundo plano. Isso é bom para o tempo de resposta, mas cria um risco
novo: a cópia pode falhar sem ninguém ver. A tela continua respondendo — com o
dado anterior — e a falha fica só no log do servidor.

Esta tela existe para essa falha ter onde aparecer, e para quem precisa do dado
de agora poder forçar a atualização sem esperar a validade vencer.

Espelha o Super77 do dash_adl, que mostra dataset, última execução, status e
linhas pelo mesmo motivo.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from app import catworld_espelho as espelho
from app.auth import is_admin as _is_admin
from app.template_config import templates
from app.utils import flash_from_request, redirect_with_message

router = APIRouter(tags=["super77"])


# Tabelas que os painéis consomem. Ficam declaradas para a tela poder mostrar
# "nunca sincronizada" — sem isso, uma tabela que nunca copiou simplesmente não
# apareceria, que é justamente o caso que se quer enxergar.
TABELAS_ESPELHADAS = [
    ("rel_colab_77", "Colaboradores (Feedz)",
     "Headcount, Turnover e Afastamentos"),
    ("ifractal_hora_extra", "Horas extras (ponto)",
     "Painel de Horas Extras"),
    ("ifractal_extrato_banco_horas", "Banco de horas (ponto)",
     "Painel de Banco de Horas"),
]


def _minutos_desde(quando: datetime | None) -> int | None:
    if not quando:
        return None
    return int((datetime.now() - quando).total_seconds() // 60)


def _idade_texto(minutos: int | None) -> str:
    if minutos is None:
        return "—"
    if minutos < 1:
        return "agora"
    if minutos < 60:
        return f"há {minutos} min"
    horas = minutos // 60
    if horas < 24:
        return f"há {horas}h"
    return f"há {horas // 24}d"


def _linhas_do_painel() -> list[dict]:
    saida = []
    for tabela, titulo, usada_por in TABELAS_ESPELHADAS:
        st = espelho.status(tabela) or {}
        quando = st.get("sincronizado_em")
        minutos = _minutos_desde(quando)
        vencida = minutos is not None and minutos >= espelho.VALIDADE_MIN

        if st.get("erro"):
            situacao, classe = "Erro na última tentativa", "erro"
        elif not quando:
            situacao, classe = "Nunca sincronizada", "erro"
        elif vencida:
            situacao, classe = "Vencida — atualiza na próxima visita", "atencao"
        else:
            situacao, classe = "Em dia", "ok"

        saida.append({
            "tabela": tabela,
            "titulo": titulo,
            "usada_por": usada_por,
            "quando": quando.strftime("%d/%m/%Y às %H:%M") if quando else "—",
            "idade": _idade_texto(minutos),
            "linhas": st.get("linhas") or 0,
            "duracao": f"{st['duracao_ms'] / 1000:.1f}s" if st.get("duracao_ms") else "—",
            "erro": st.get("erro") or "",
            "situacao": situacao,
            "classe": classe,
        })
    return saida


@router.get("/super77")
def super77_home(request: Request):
    if not _is_admin(request):
        return RedirectResponse("/?sem_acesso=super77", status_code=303)
    return templates.TemplateResponse("super77/index.html", {
        "request": request,
        "tabelas": _linhas_do_painel(),
        "validade_min": espelho.VALIDADE_MIN,
        # sem isto o botão redireciona com a mensagem na URL e a tela não
        # mostra nada — botão sem resposta, que é o defeito que esta tela
        # existe para evitar
        **flash_from_request(request),
    })


@router.post("/super77/atualizar")
def super77_atualizar(request: Request, tabela: str = Form("")):
    """Força a cópia agora, sem esperar a validade vencer.

    Roda na própria requisição de propósito: quem clicou quer saber se deu
    certo, e mandar para segundo plano devolveria a tela sem resposta — o
    mesmo problema que o botão de sincronizar do Facilities tinha.
    """
    if not _is_admin(request):
        return RedirectResponse("/?sem_acesso=super77", status_code=303)

    from app.routers.indicadores import _buscar_catworld_direto

    alvos = [tabela] if tabela else [t for t, _, _ in TABELAS_ESPELHADAS]
    ok, falhas = [], []
    for alvo in alvos:
        resultado = espelho.atualizar(alvo, _buscar_catworld_direto)
        if resultado.get("ok"):
            ok.append(f"{alvo}: {resultado['linhas']} linhas "
                      f"em {resultado['duracao_ms'] / 1000:.1f}s")
        else:
            falhas.append(f"{alvo}: {resultado.get('erro', 'falhou')}")

    if falhas and not ok:
        return redirect_with_message(
            "/super77",
            error="Não consegui atualizar — a origem não respondeu. "
                  "O espelho anterior continua valendo. | " + " | ".join(falhas))
    if falhas:
        return redirect_with_message(
            "/super77",
            success="Atualizado: " + " | ".join(ok) + " || Falhou: " + " | ".join(falhas))
    return redirect_with_message("/super77", success="Atualizado — " + " | ".join(ok))
