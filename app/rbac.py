"""Controle de acesso por papel, permissão e recurso — o modelo do dash_tmk.

Antes o acesso era decidido por dois campos do usuário: `perfil` ("admin" ou
"operador") e `modulos_acesso`, uma lista de módulos. Isso tem três limites
que apareceram na prática:

- era tudo ou nada dentro do módulo. Liberar só o Turnover para alguém do DHO
  não era possível: ou via os sete indicadores do módulo, ou nenhum;
- `perfil == "admin"` liberava inclusive as áreas técnicas da equipe 77, que
  não são do cliente;
- não existia recorte por empresa. Quem só responde pela Dener via GT3 e
  Pires junto.

O modelo do TMK (docs/03-rbac.md) resolve os três:

    usuário → papéis → permissões                    (permissão global)
    usuário/papel → permissão + recurso              (permissão em um recurso)
    usuário → dimensão → valores                     (recorte de linhas)

Regras, as mesmas de lá:

- toda tela declara a permissão mínima;
- a interface esconde o que a pessoa não pode ver;
- o servidor confere sempre, mesmo que a interface já tenha escondido;
- `super77` é papel como qualquer outro e também passa pelo motor.
"""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import (Column, DateTime, Integer, MetaData, String, Table,
                        UniqueConstraint, delete, insert, select, text)

from app.database import engine

metadata_rbac = MetaData()

papeis = Table(
    "rbac_papeis", metadata_rbac,
    Column("chave", String(40), primary_key=True),
    Column("nome", String(120)),
    Column("descricao", String(300)),
)

permissoes = Table(
    "rbac_permissoes", metadata_rbac,
    Column("chave", String(60), primary_key=True),
    Column("descricao", String(300)),
)

papel_permissao = Table(
    "rbac_papel_permissao", metadata_rbac,
    Column("papel", String(40), primary_key=True),
    Column("permissao", String(60), primary_key=True),
)

usuario_papel = Table(
    "rbac_usuario_papel", metadata_rbac,
    Column("id_usuario", Integer, primary_key=True),
    Column("papel", String(40), primary_key=True),
)

# Permissão concedida só dentro de um recurso: um grupo de indicadores, uma
# tela, um módulo de cadastro. É aqui que mora "vê o Turnover e mais nada".
politica_recurso = Table(
    "rbac_politica_recurso", metadata_rbac,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("id_usuario", Integer, index=True),
    Column("permissao", String(60)),
    Column("tipo_recurso", String(40)),
    Column("id_recurso", String(120)),
    UniqueConstraint("id_usuario", "permissao", "tipo_recurso", "id_recurso",
                     name="ux_politica"),
)

# Recorte de LINHAS, não de telas. Sem nenhum valor numa dimensão, a pessoa vê
# tudo daquela dimensão — é o comportamento de quem administra.
usuario_escopo = Table(
    "rbac_usuario_escopo", metadata_rbac,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("id_usuario", Integer, index=True),
    Column("dimensao", String(40)),
    Column("valor", String(120)),
    UniqueConstraint("id_usuario", "dimensao", "valor", name="ux_escopo"),
)

rbac_controle = Table(
    "rbac_controle", metadata_rbac,
    Column("chave", String(40), primary_key=True),
    Column("valor", String(200)),
    Column("em", DateTime),
)


# ─── permissões ───────────────────────────────────────────────────────────────

PERMISSOES = {
    "indicators.group.view": "Ver um grupo de indicadores",
    "indicators.dashboard.view": "Ver uma tela de indicador",
    "registries.module.view": "Abrir um módulo de cadastro",
    "registries.record.manage": "Criar e alterar registros",
    "exports.excel.create": "Exportar para Excel",
    "integrations.catworld.view": "Ver a integração com o Catworld",
    "integrations.catworld.manage": "Operar a integração com o Catworld",
    "system.jobs.view": "Ver sincronizações e rotinas",
    "system.logs.view": "Ver os logs do sistema",
    "system.settings.manage": "Alterar configurações do sistema",
    "users.manage": "Gerenciar usuários e acessos",
    "super77.access": "Acessar as áreas técnicas da equipe 77",
}

PAPEIS = {
    "admin": ("Administrador", "Administra o sistema do cliente", [
        "indicators.group.view", "indicators.dashboard.view",
        "registries.module.view", "registries.record.manage",
        "exports.excel.create", "integrations.catworld.view",
        "system.jobs.view", "system.logs.view", "system.settings.manage",
        "users.manage",
    ]),
    # A equipe 77 dentro do sistema do cliente. Separado de admin de propósito:
    # área técnica não é do cliente, e administrar o cliente não é da 77.
    "super77": ("Equipe 77", "Suporte técnico da 77", [
        "super77.access", "integrations.catworld.view",
        "integrations.catworld.manage", "system.jobs.view",
        "system.logs.view", "system.settings.manage", "users.manage",
    ]),
    # Não traz permissão de tela nenhuma: o que esta pessoa enxerga é
    # concedido recurso a recurso, na tela de Usuários.
    "operador": ("Operador", "Vê apenas o que for liberado", [
        "exports.excel.create",
    ]),
}

TIPO_GRUPO = "dashboard_group"
TIPO_TELA = "dashboard_screen"
TIPO_CADASTRO = "registry_module"


# ─── catálogo: o que existe para ser liberado ─────────────────────────────────

GRUPOS = [
    {"slug": "dho", "nome": "DHO", "telas": [
        ("dho.headcount", "Headcount Ativo", "/indicadores/headcount"),
        ("dho.turnover", "Turnover", "/indicadores/turnover"),
        ("dho.banco-horas", "Banco de Horas", "/indicadores/banco-horas"),
        ("dho.horas-extras", "Horas Extras", "/indicadores/horas-extras"),
        ("dho.afastamentos", "Afastamentos", "/indicadores/afastamentos"),
        ("dho.treinamentos", "Treinamentos", "/indicadores/treinamentos"),
        ("dho.vagas", "Vagas", "/indicadores/vagas"),
    ]},
    {"slug": "folha", "nome": "Folha de Pagamento", "telas": [
        ("folha.visao-custo", "Visão Custo Empresa", "/indicadores/folha-visao-custo"),
        ("folha.variacao", "Variação de Custo", "/indicadores/folha-variacao"),
        ("folha.holerite", "Holerite Colaborador", "/indicadores/folha-holerite"),
        ("folha.lista", "Holerite · Lista", "/indicadores/folha-lista"),
        ("folha.simulacao", "Simulação de Aumento", "/indicadores/folha-simulacao"),
        ("folha.custo-colaborador", "Custo por Colaborador", "/indicadores/folha-custo-colaborador"),
    ]},
    {"slug": "facilities", "nome": "Facilities", "telas": [
        ("facilities.painel", "Painel de Facilities", "/indicadores/facilities"),
    ]},
    {"slug": "autonomos", "nome": "Autônomos", "telas": [
        ("autonomos.custo", "Custo 1", "/indicadores/autonomo-custo"),
        ("autonomos.custo2", "Custo 2", "/indicadores/autonomo-custo2"),
        ("autonomos.custo-evolucao", "Custo · Evolução", "/indicadores/autonomo-custo-evolucao"),
        ("autonomos.custo-pagamentos", "Custo · Pagamentos", "/indicadores/autonomo-custo-pagamentos"),
        ("autonomos.disponibilidade", "Planejamento e Cobertura", "/indicadores/autonomo-disponibilidade"),
        ("autonomos.trocas", "Trocas e Continuidade", "/indicadores/autonomo-trocas"),
        ("autonomos.pesquisas", "Pesquisas", "/indicadores/pesquisas"),
    ]},
]

# Cadastros: o prefixo de rota é o que o servidor confere.
CADASTROS = [
    {"slug": "dho", "nome": "Cadastros do DHO", "prefixos": ["/dho"]},
    {"slug": "folha", "nome": "Folha de Pagamento", "prefixos": ["/folha", "/budget"]},
    {"slug": "facilities", "nome": "Gestão Facilities", "prefixos": ["/facilities"]},
    {"slug": "autonomos", "nome": "Autônomos e Equipes", "prefixos": [
        "/cadastros", "/equipes", "/equipe-geral", "/alocacoes", "/carros",
        "/troca-etapas", "/autonomo-sede", "/pesquisas", "/relatorios",
        "/composicao-meta-equipe", "/atestados"]},
]

# Áreas técnicas e de sistema: rota → permissão exigida, como o ROUTE_PERMISSIONS
# do TMK. O prefixo mais longo que casar é o que vale.
ROTA_PERMISSAO = {
    "/super77": "super77.access",
    "/usuarios": "users.manage",
    "/logs": "system.logs.view",
    "/importacoes": "system.settings.manage",
    "/referencias-importacao": "system.settings.manage",
    "/setup": "system.settings.manage",
    "/wizard": "system.settings.manage",
    "/listas-apoio": "system.settings.manage",
    "/atualizar-cadastros": "system.jobs.view",
    "/excel": "system.settings.manage",
    "/ids-importacao": "system.settings.manage",
    "/autonomos/atualizar-excel": "system.settings.manage",
    "/debug": "super77.access",
}

TELA_POR_ROTA = {rota: (g["slug"], slug)
                 for g in GRUPOS for slug, _nome, rota in g["telas"]}


def grupo_da_tela(slug_tela: str) -> str:
    return slug_tela.split(".", 1)[0]


# ─── criação e semeadura ──────────────────────────────────────────────────────

def _criar_tabelas():
    try:
        metadata_rbac.create_all(engine)
    except Exception as exc:
        print(f"AVISO - não consegui criar as tabelas de acesso: {exc}")


def semear():
    """Permissões e papéis são catálogo, não dado do cliente: sempre conferidos."""
    try:
        with engine.begin() as cx:
            atuais = {r[0] for r in cx.execute(select(permissoes.c.chave))}
            for chave, desc in PERMISSOES.items():
                if chave not in atuais:
                    cx.execute(insert(permissoes).values(chave=chave, descricao=desc))
            papeis_atuais = {r[0] for r in cx.execute(select(papeis.c.chave))}
            for chave, (nome, desc, perms) in PAPEIS.items():
                if chave not in papeis_atuais:
                    cx.execute(insert(papeis).values(chave=chave, nome=nome, descricao=desc))
                tem = {r[0] for r in cx.execute(
                    select(papel_permissao.c.permissao).where(papel_permissao.c.papel == chave))}
                for p in perms:
                    if p not in tem:
                        cx.execute(insert(papel_permissao).values(papel=chave, permissao=p))
    except Exception as exc:
        print(f"AVISO - não consegui semear papéis e permissões: {exc}")


def _ja_migrou() -> bool:
    try:
        with engine.connect() as cx:
            r = cx.execute(select(rbac_controle.c.valor)
                           .where(rbac_controle.c.chave == "migracao_perfil")).first()
        return bool(r)
    except Exception:
        return True   # na dúvida não mexe


def migrar_do_perfil():
    """Converte `perfil` + `modulos_acesso` em papéis e políticas, uma vez.

    Sem isso, ligar o motor novo tiraria o acesso de todo mundo no mesmo
    instante. Quem era admin vira admin; quem era operador vira operador com
    os módulos que já tinha liberados — e quem não tinha nenhum módulo
    marcado (que no modelo antigo queria dizer "vê tudo") recebe todos.
    """
    if _ja_migrou():
        return
    try:
        with engine.begin() as cx:
            usuarios = cx.execute(text(
                "SELECT id_usuario, email, perfil, modulos_acesso FROM usuarios")).mappings().all()
            for u in usuarios:
                uid = u["id_usuario"]
                perfil = (u["perfil"] or "").strip().lower()
                papel = "admin" if perfil == "admin" else "operador"
                cx.execute(insert(usuario_papel).values(id_usuario=uid, papel=papel))
                if papel == "admin":
                    continue
                try:
                    mods = json.loads(u["modulos_acesso"] or "[]")
                except Exception:
                    mods = []
                if not mods:          # lista vazia no modelo antigo = tudo
                    mods = [g["slug"] for g in GRUPOS]
                for slug in mods:
                    cx.execute(insert(politica_recurso).values(
                        id_usuario=uid, permissao="indicators.group.view",
                        tipo_recurso=TIPO_GRUPO, id_recurso=slug))
                    cx.execute(insert(politica_recurso).values(
                        id_usuario=uid, permissao="registries.module.view",
                        tipo_recurso=TIPO_CADASTRO, id_recurso=slug))
            cx.execute(insert(rbac_controle).values(
                chave="migracao_perfil", valor=f"{len(usuarios)} usuários",
                em=datetime.now()))
        print(f"RBAC: {len(usuarios)} usuários migrados do perfil para papéis.")
    except Exception as exc:
        print(f"AVISO - não consegui migrar os acessos antigos: {exc}")


_criar_tabelas()
semear()
migrar_do_perfil()


# ─── consulta ─────────────────────────────────────────────────────────────────

def papeis_do_usuario(id_usuario) -> list[str]:
    if not id_usuario:
        return []
    with engine.connect() as cx:
        return [r[0] for r in cx.execute(
            select(usuario_papel.c.papel).where(usuario_papel.c.id_usuario == int(id_usuario)))]


def permissoes_do_usuario(id_usuario) -> set[str]:
    """Permissões globais, vindas dos papéis."""
    lista = papeis_do_usuario(id_usuario)
    if not lista:
        return set()
    with engine.connect() as cx:
        return {r[0] for r in cx.execute(
            select(papel_permissao.c.permissao).where(papel_permissao.c.papel.in_(lista)))}


def politicas_do_usuario(id_usuario) -> set[tuple[str, str, str]]:
    """(permissão, tipo de recurso, recurso) concedidos ao usuário."""
    if not id_usuario:
        return set()
    with engine.connect() as cx:
        return {(r[0], r[1], r[2]) for r in cx.execute(
            select(politica_recurso.c.permissao, politica_recurso.c.tipo_recurso,
                   politica_recurso.c.id_recurso)
            .where(politica_recurso.c.id_usuario == int(id_usuario)))}


def escopo_do_usuario(id_usuario) -> dict[str, list[str]]:
    """Dimensão → valores permitidos. Dimensão ausente quer dizer "vê tudo"."""
    if not id_usuario:
        return {}
    mapa: dict[str, list[str]] = {}
    with engine.connect() as cx:
        for dim, val in cx.execute(
                select(usuario_escopo.c.dimensao, usuario_escopo.c.valor)
                .where(usuario_escopo.c.id_usuario == int(id_usuario))):
            mapa.setdefault(dim, []).append(val)
    return mapa


def filtrar_escopo(mapa: dict[str, list[str]], dimensao: str, valores):
    """Aplica o recorte a uma lista de valores já conhecida.

    Sem escopo na dimensão, devolve tudo — é o comportamento de quem
    administra, igual ao scopeFilter do TMK.
    """
    permitidos = mapa.get(dimensao)
    if not permitidos:
        return list(valores)
    alvo = {str(v).strip().upper() for v in permitidos}
    return [v for v in valores if str(v).strip().upper() in alvo]


# ─── no pedido ────────────────────────────────────────────────────────────────

def _usuario(request):
    return getattr(request.state, "current_user", None) or {}


def contexto(request) -> dict:
    """Permissões, políticas e escopo do usuário do pedido, carregados uma vez.

    Fica em request.state: uma tela chega a perguntar por dezenas de recursos
    ao montar o menu, e cada pergunta era uma ida ao banco.
    """
    pronto = getattr(request.state, "_rbac", None)
    if pronto is not None:
        return pronto
    u = _usuario(request)
    uid = u.get("id_usuario")
    ctx = {
        "permissoes": permissoes_do_usuario(uid) if uid else set(),
        "politicas": politicas_do_usuario(uid) if uid else set(),
        "escopo": escopo_do_usuario(uid) if uid else {},
    }
    # Sem papel nenhum, vale o perfil antigo. Cobre o auto-login local, o
    # usuário criado antes da migração e qualquer falha ao migrar: ninguém
    # fica trancado do lado de fora por causa da troca de modelo.
    if u and not ctx["permissoes"] and (u.get("perfil") or "").lower() == "admin":
        ctx["permissoes"] = set(PAPEIS["admin"][2])
    request.state._rbac = ctx
    return ctx


def tem_permissao(request, chave: str) -> bool:
    return chave in contexto(request)["permissoes"]


def tem_permissao_no_recurso(request, chave: str, tipo: str, recurso: str) -> bool:
    """Global pelo papel OU concedida naquele recurso. Mesma ordem do TMK."""
    ctx = contexto(request)
    if chave in ctx["permissoes"]:
        return True
    return (chave, tipo, recurso) in ctx["politicas"]


def pode_ver_tela(request, rota: str) -> bool:
    alvo = TELA_POR_ROTA.get(rota.rstrip("/") or "/")
    if not alvo:
        return True                       # tela fora do catálogo não é restrita aqui
    grupo, tela = alvo
    # Liberar o grupo libera as telas dele; liberar só a tela também vale.
    return (tem_permissao_no_recurso(request, "indicators.dashboard.view", TIPO_TELA, tela)
            or tem_permissao_no_recurso(request, "indicators.group.view", TIPO_GRUPO, grupo))


def pode_ver_cadastro(request, slug: str) -> bool:
    return tem_permissao_no_recurso(request, "registries.module.view", TIPO_CADASTRO, slug)


def telas_visiveis(request) -> set[str]:
    """Rotas de indicador que a pessoa pode abrir — para o menu."""
    return {rota for rota in TELA_POR_ROTA if pode_ver_tela(request, rota)}


def grupos_visiveis(request) -> set[str]:
    return {g["slug"] for g in GRUPOS
            if any(pode_ver_tela(request, rota) for _s, _n, rota in g["telas"])}


def cadastro_da_rota(path: str) -> str:
    """Módulo de cadastro a que a rota pertence, pelo prefixo mais longo."""
    melhor, tamanho = "", 0
    for c in CADASTROS:
        for pref in c["prefixos"]:
            if (path == pref or path.startswith(pref + "/")) and len(pref) > tamanho:
                melhor, tamanho = c["slug"], len(pref)
    return melhor


def exigencia_da_rota(path: str):
    """O que a rota exige: (permissão, tipo de recurso, recurso) ou None.

    É a tradução do ROUTE_PERMISSIONS do TMK, com os recursos deste sistema.
    """
    path = path.rstrip("/") or "/"
    alvo = TELA_POR_ROTA.get(path)
    if alvo:
        return ("indicators.dashboard.view", TIPO_TELA, alvo[1])
    melhor = ""
    for pref in ROTA_PERMISSAO:
        if (path == pref or path.startswith(pref + "/")) and len(pref) > len(melhor):
            melhor = pref
    if melhor:
        return (ROTA_PERMISSAO[melhor], "", "")
    slug = cadastro_da_rota(path)
    if slug:
        return ("registries.module.view", TIPO_CADASTRO, slug)
    return None


def pode_acessar_rota(request, path: str) -> bool:
    exig = exigencia_da_rota(path)
    if exig is None:
        return True
    chave, tipo, recurso = exig
    if not tipo:
        return tem_permissao(request, chave)
    if tipo == TIPO_TELA:
        return pode_ver_tela(request, path)
    return tem_permissao_no_recurso(request, chave, tipo, recurso)


def escopo(request, dimensao: str) -> list[str]:
    return contexto(request)["escopo"].get(dimensao, [])


# ─── escrita (tela de Usuários) ───────────────────────────────────────────────

# Dimensões oferecidas na tela. "empresa" casa com a UNIDADE do Catworld, que
# é onde Dener, Pires e GT3 aparecem; a comparação é sem diferenciar maiúsculas.
DIMENSOES = {"empresa": ["DENER", "PIRES", "GT3"]}


def definir_papeis(id_usuario, lista: list[str]):
    uid = int(id_usuario)
    validos = [p for p in lista if p in PAPEIS]
    with engine.begin() as cx:
        cx.execute(delete(usuario_papel).where(usuario_papel.c.id_usuario == uid))
        for p in validos:
            cx.execute(insert(usuario_papel).values(id_usuario=uid, papel=p))


def definir_politicas(id_usuario, grupos: list[str], telas: list[str], cadastros: list[str]):
    """Substitui as concessões de recurso do usuário.

    Concessão é por usuário, não por papel: papel é permissão global, declarada
    no catálogo. Igual ao policies.ts do TMK.
    """
    uid = int(id_usuario)
    slugs_grupo = {g["slug"] for g in GRUPOS}
    slugs_tela = {s for g in GRUPOS for s, _n, _r in g["telas"]}
    slugs_cad = {c["slug"] for c in CADASTROS}
    novas = (
        [("indicators.group.view", TIPO_GRUPO, s) for s in grupos if s in slugs_grupo]
        + [("indicators.dashboard.view", TIPO_TELA, s) for s in telas if s in slugs_tela]
        + [("registries.module.view", TIPO_CADASTRO, s) for s in cadastros if s in slugs_cad]
    )
    with engine.begin() as cx:
        cx.execute(delete(politica_recurso).where(politica_recurso.c.id_usuario == uid))
        for perm, tipo, rec in novas:
            cx.execute(insert(politica_recurso).values(
                id_usuario=uid, permissao=perm, tipo_recurso=tipo, id_recurso=rec))


def definir_escopo(id_usuario, dimensao: str, valores: list[str]):
    """Nenhum valor = vê tudo naquela dimensão."""
    uid = int(id_usuario)
    with engine.begin() as cx:
        cx.execute(delete(usuario_escopo)
                   .where(usuario_escopo.c.id_usuario == uid)
                   .where(usuario_escopo.c.dimensao == dimensao))
        for v in dict.fromkeys(v.strip() for v in valores if v.strip()):
            cx.execute(insert(usuario_escopo).values(
                id_usuario=uid, dimensao=dimensao, valor=v))


def concessoes_do_usuario(id_usuario) -> dict:
    """O que a tela de Usuários precisa marcar."""
    pol = politicas_do_usuario(id_usuario)
    return {
        "papeis": papeis_do_usuario(id_usuario),
        "grupos": sorted(r for p, t, r in pol if t == TIPO_GRUPO),
        "telas": sorted(r for p, t, r in pol if t == TIPO_TELA),
        "cadastros": sorted(r for p, t, r in pol if t == TIPO_CADASTRO),
        "escopo": escopo_do_usuario(id_usuario),
    }
