"""Módulo Budget de Pessoal.

Parte do Folha de Pagamento.
Parte da base realizada (salário + periculosidade do folha_funcionarios /
folha_rubricas) e projeta os custos via cadastros parametrizados com vigência.

Ordem de prioridade das regras (maior → menor):
  1. Exceção específica do empregado
  2. Empresa + empregado
  3. Empresa + cargo
  4. Empresa + grupo de cargo
  5. Cargo (geral)
  6. Vínculo
  7. Regra geral do sistema
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    delete,
    insert,
    select,
    text,
    update,
)
from sqlalchemy.orm import Session

from app.database import engine, get_db
from app.template_config import templates
from app.utils import redirect_with_message

router = APIRouter(tags=["budget"])

metadata_budget = MetaData()

_CARGOS_PADRAO_TEXTO = """
{"ADESIVADOR", "Ajudante", "Operacional", "Bate Ponto", 0.25, 0.25},
{"AJ MANUTENÇÃO PREDIAL", "Ajudante", "Administrativo", "Bate Ponto", 0, 0},
{"AJUDANTE MECANICO", "Ajudante", "Administrativo", "Bate Ponto", 0.25, 0.25},
{"ANALISTA ALMOXARIFADO PL", "Analistas", "Administrativo", "Bate Ponto", 0.25, 0.25},
{"ANALISTA DE EVENTOS SR", "Analistas", "Administrativo", "Bate Ponto", 0.25, 0.25},
{"ANALISTA DE LOGISTICA JR", "Analistas", "Administrativo", "Bate Ponto", 0.25, 0.25},
{"ANALISTA DE PEÇAS PL", "Analistas", "Administrativo", "Bate Ponto", 0.25, 0.25},
{"ANALISTA DE PLANEJAMENTO E RELACIONAMEN", "Analistas", "Administrativo", "Bate Ponto", 0.25, 0.25},
{"ANALISTA PEÇAS JR", "Analistas", "Administrativo", "Bate Ponto", 0.25, 0.25},
{"ANLTA ALMOXARIFADO SR", "Analistas", "Administrativo", "Bate Ponto", 0.25, 0.25},
{"ANLTA DEPTO PESSOAL JR", "Analistas", "Administrativo", "Bate Ponto", 0, 0},
{"ANLTA DPTO PESSOAL SR", "Analistas", "Administrativo", "Bate Ponto", 0, 0},
{"ANLTA ENGENHARIA JR", "Analistas", "Administrativo", "Bate Ponto", 0.25, 0.25},
{"ANLTA ENGENHARIA PL", "Analistas", "Administrativo", "Bate Ponto", 0.25, 0.25},
{"ANLTA ENGENHARIA SR", "Analistas", "Administrativo", "Bate Ponto", 0.25, 0.25},
{"ANLTA FINANCEIRO PL", "Analistas", "Administrativo", "Bate Ponto", 0, 0},
{"ANLTA FINANCEIRO SR", "Analistas", "Administrativo", "Bate Ponto", 0, 0},
{"ANLTA LOGISTICA", "Analistas", "Administrativo", "Bate Ponto", 0.25, 0.25},
{"ANLTA LOGISTICA JR", "Analistas", "Administrativo", "Bate Ponto", 0.25, 0.25},
{"ANLTA MARKETING JR", "Analistas", "Administrativo", "Bate Ponto", 0.25, 0.25},
{"ANLTA MARKETING MIDIAS PL", "Analistas", "Administrativo", "Bate Ponto", 0.25, 0.25},
{"ANLTA MARKETING SENIOR", "Analistas", "Administrativo", "Bate Ponto", 0.25, 0.25},
{"ANLTA RH PLENO", "Analistas", "Administrativo", "Bate Ponto", 0.25, 0.25},
{"ANLTA RH SR", "Analistas", "Administrativo", "Bate Ponto", 0.25, 0.25},
{"APRENDIZ", "Aprendiz", "Administrativo", "Bate Ponto", 0, 0},
{"ASSIST ADMINISTRATIVO", "Assistentes", "Administrativo", "Bate Ponto", 0, 0},
{"ASSIST EXECUTIVA", "Assistentes", "Administrativo", "Bate Ponto", 0.25, 0.25},
{"ASSISTENTE COMPRAS", "Assistentes", "Administrativo", "Bate Ponto", 0.25, 0.25},
{"ASSISTENTE DE EVENTOS", "Assistentes", "Administrativo", "Bate Ponto", 0.25, 0.25},
{"ASSISTENTE DE PEÇAS", "Assistentes", "Administrativo", "Bate Ponto", 0.25, 0.25},
{"AUTONOMO", "Autonomo", "Diversos", "Não Bate Ponto", 0.25, 0.25},
{"AUX ESTOQUE", "Auxiliares", "Administrativo", "Bate Ponto", 0.25, 0.25},
{"AUXILIAR ALMOXARIFADO", "Auxiliares", "Administrativo", "Bate Ponto", 0.25, 0.25},
{"COORD ENGENHARIA", "Coordenadores", "Coordenação", "Não Bate Ponto", 0.25, 0.25},
{"COORD MARKETING", "Coordenadores", "Coordenação", "Não Bate Ponto", 0.25, 0.25},
{"COORDENADOR PEÇAS", "Coordenadores", "Coordenação", "Não Bate Ponto", 0.25, 0.25},
{"COPEIRA", "Auxiliares", "Operacional", "Bate Ponto", 0, 0},
{"DESIGN JR", "Analistas", "Operacional", "Bate Ponto", 0.25, 0.25},
{"DESIGNER GRAFICO", "Analistas", "Operacional", "Bate Ponto", 0.25, 0.25},
{"DIRETOR DE OPERACOES", "Diretor", "Diretoria", "Não Bate Ponto", 0.25, 0.25},
{"ENCARREGADO DE OFICINA", "Coordenadores", "Operacional", "Não Bate Ponto", 0.25, 0.25},
{"ESPECIALISTA DE LOGISTICA", "Especialista", "Administrativo", "Não Bate Ponto", 0.25, 0.25},
{"ESPECIALISTA EM EVENTOS", "Especialista", "Administrativo", "Não Bate Ponto", 0.25, 0.25},
{"ESTAGIARIA", "Estagiario", "Estagiario", "Não Bate Ponto", 0, 0},
{"ESTAGIARIO", "Estagiario", "Estagiario", "Não Bate Ponto", 0, 0},
{"ESTOQUISTA", "Estoquista", "Operacional", "Bate Ponto", 0.25, 0.25},
{"FUNILEIRO MECANICO JR", "Funileiro", "Operacional", "Bate Ponto", 0.25, 0.25},
{"FUNILEIRO MECANICO PL", "Funileiro", "Operacional", "Bate Ponto", 0.25, 0.25},
{"FUNILEIRO MECANICO SR", "Funileiro", "Operacional", "Bate Ponto", 0.25, 0.25},
{"GERENTE DE LOGISTICA", "Gerente", "Gerencia", "Não Bate Ponto", 0.25, 0.25},
{"GERENTE ENGENHARIA", "Gerente", "Gerencia", "Não Bate Ponto", 0.25, 0.25},
{"GERENTE ENGENHARIA DE QUALIDADE", "Gerente", "Gerencia", "Não Bate Ponto", 0.25, 0.25},
{"GERENTE EVENTOS", "Gerente", "Gerencia", "Não Bate Ponto", 0.25, 0.25},
{"GERENTE RECURSOS HUMANOS", "Gerente", "Gerencia", "Não Bate Ponto", 0.25, 0.25},
{"LIDER DE ENGENHARIA", "Lider", "Operacional", "Bate Ponto", 0.25, 0.25},
{"LIDER DE FUNILARIA", "Lider", "Operacional", "Bate Ponto", 0.25, 0.25},
{"MECANICO COMPETIÇÃO JR", "Mecanico", "Operacional", "Bate Ponto", 0.25, 0.25},
{"MECANICO COMPETIÇAO PL", "Mecanico", "Operacional", "Bate Ponto", 0.25, 0.25},
{"MECANICO COMPETIÇÃO SR", "Mecanico", "Operacional", "Bate Ponto", 0.25, 0.25},
{"MONTADOR DE AUTOS JR", "Montador", "Operacional", "Bate Ponto", 0.25, 0.25},
{"MOTORISTA DE CAMINHÃO", "Motorista", "Operacional", "Bate Ponto", 0.25, 0.25},
{"MOTORISTA DE CAMINHAO PL", "Motorista", "Operacional", "Bate Ponto", 0.25, 0.25},
{"OFICIAL DE MANUTEN PREDIAL", "Oficial", "Operacional", "Bate Ponto", 0, 0},
{"OPERADOR MAQUINA PLOTTER", "Operador", "Operacional", "Bate Ponto", 0.25, 0.25},
{"PRODUTOR EXECUTIVO DE MIDIAS AUDIOVISUACI", "Produtor", "Operacional", "Bate Ponto", 0.25, 0.25},
{"SERRALHEIRO PL", "Serralheiro", "Operacional", "Bate Ponto", 0.25, 0.25},
{"SOCIO", "Socio", "Diretoria", "Não Bate Ponto", 0, 0},
{"SUP ADMINISTRATIVO", "Supervisor", "Operacional", "Não Bate Ponto", 0.25, 0.25},
{"SUP MANUTENÇÃO", "Supervisor", "Operacional", "Não Bate Ponto", 0.25, 0.25},
{"SUP MANUTENCAO MECANICA", "Supervisor", "Operacional", "Não Bate Ponto", 0.25, 0.25},
{"SUPERVISOR ADESIVAGEM", "Supervisor", "Operacional", "Não Bate Ponto", 0.25, 0.25},
{"SUPERVISOR DE EVENTOS", "Supervisor", "Operacional", "Não Bate Ponto", 0.25, 0.25},
{"SUPERVISOR MANUTENÇAO MECANICA", "Supervisor", "Operacional", "Não Bate Ponto", 0.25, 0.25}
"""


def _normalizar_cargo(valor: str | None) -> str:
    texto = unicodedata.normalize("NFKD", valor or "")
    texto = "".join(ch for ch in texto if not unicodedata.combining(ch))
    texto = re.sub(r"[^A-Z0-9]+", " ", texto.upper())
    return re.sub(r"\s+", " ", texto).strip()


def _carregar_cargos_padrao() -> dict[str, dict[str, Any]]:
    regras: dict[str, dict[str, Any]] = {}
    for cargo, nivel1, nivel2, ponto, pct25, pct_he in re.findall(
        r'\{"([^"]+)",\s*"([^"]+)",\s*"([^"]+)",\s*"([^"]+)",\s*([0-9.]+),\s*([0-9.]+)\}',
        _CARGOS_PADRAO_TEXTO,
    ):
        regras[_normalizar_cargo(cargo)] = {
            "cargo_original": cargo,
            "nivel1": nivel1,
            "nivel2": nivel2,
            "nivel3": ponto,
            "tem_periculosidade": False,
            "bate_ponto": _normalizar_cargo(ponto) == "BATE PONTO",
            "pct_adicional_25": float(pct25),
            "pct_he_sobre_25": float(pct_he),
            "pode_he": _normalizar_cargo(ponto) == "BATE PONTO",
        }
    return regras


CARGOS_PADRAO = _carregar_cargos_padrao()


def _parametros_padrao_cargo(cargo: str | None) -> dict[str, Any]:
    return CARGOS_PADRAO.get(_normalizar_cargo(cargo), {
        "nivel1": "",
        "nivel2": "",
        "nivel3": "Bate Ponto",
        "tem_periculosidade": False,
        "bate_ponto": True,
        "pct_adicional_25": 0.0,
        "pct_he_sobre_25": 0.0,
        "pode_he": True,
    })

# ─────────────────────────────────────────────────────────────
# TABELAS
# ─────────────────────────────────────────────────────────────

budget_empresas = Table(
    "budget_empresas", metadata_budget,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("codigo", String(20), nullable=False),
    Column("razao_social", String(255), nullable=False),
    Column("cnpj", String(30)),
    Column("status", String(20), default="Ativo"),
    Column("vigencia_inicio", String(10)),
    Column("vigencia_fim", String(10)),
    Column("criado_em", DateTime, default=datetime.utcnow),
    Column("criado_por", String(120)),
)

budget_vinculos = Table(
    "budget_vinculos", metadata_budget,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("codigo", String(40), nullable=False),
    Column("descricao", String(120)),
    Column("tem_fgts", Boolean, default=True),
    Column("tem_inss_patronal", Boolean, default=True),
    Column("tem_decimo_terceiro", Boolean, default=True),
    Column("tem_ferias", Boolean, default=True),
    Column("tem_um_terco", Boolean, default=True),
    Column("tem_aviso_previo", Boolean, default=True),
    Column("tem_plr", Boolean, default=True),
    Column("pode_he", Boolean, default=True),
    Column("pode_beneficios", Boolean, default=True),
    Column("status", String(20), default="Ativo"),
    Column("vigencia_inicio", String(10)),
    Column("vigencia_fim", String(10)),
    Column("criado_em", DateTime, default=datetime.utcnow),
    Column("criado_por", String(120)),
)

budget_cargos = Table(
    "budget_cargos", metadata_budget,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("competencia", String(20)),
    Column("codigo_cargo", String(40), nullable=False),
    Column("matricula", String(40)),
    Column("nome", String(200)),
    Column("descricao", String(200)),
    Column("salario", Float, default=0.0),
    Column("horas_mes", Float, default=200.0),
    Column("dependentes", Integer, default=0),
    Column("tem_periculosidade", Boolean, default=False),
    Column("bate_ponto", Boolean, default=True),
    Column("pct_adicional_25", Float, default=0.0),
    Column("pct_he_sobre_25", Float, default=0.0),
    # flags de vínculo por cargo
    Column("tem_fgts", Boolean, default=True),
    Column("tem_inss", Boolean, default=True),
    Column("tem_d13", Boolean, default=True),
    Column("tem_ferias", Boolean, default=True),
    Column("tem_terca", Boolean, default=True),
    Column("tem_aviso", Boolean, default=True),
    Column("tem_plr", Boolean, default=False),
    Column("pode_he", Boolean, default=True),
    Column("pode_beneficios", Boolean, default=True),
    Column("status", String(20), default="Ativo"),
    Column("vigencia_inicio", String(10)),
    Column("vigencia_fim", String(10)),
    Column("criado_em", DateTime, default=datetime.utcnow),
    Column("criado_por", String(120)),
)

budget_cargos_niveis = Table(
    "budget_cargos_niveis", metadata_budget,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("cargo", String(200), nullable=False),
    Column("cargo_normalizado", String(220), nullable=False),
    Column("nivel1", String(80)),
    Column("nivel2", String(80)),
    Column("nivel3", String(80)),
    Column("tem_periculosidade", Boolean, default=False),
    Column("bate_ponto", Boolean, default=True),
    Column("pct_adicional_25", Float, default=0.0),
    Column("pct_he_sobre_25", Float, default=0.0),
    Column("pode_he", Boolean, default=True),
    Column("status", String(20), default="Ativo"),
    Column("criado_em", DateTime, default=datetime.utcnow),
    Column("criado_por", String(120)),
)

budget_verbas = Table(
    "budget_verbas", metadata_budget,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("codigo", String(20), nullable=False),
    Column("descricao", String(200), nullable=False),
    Column("categoria", String(40)),          # remuneracao, adicional, he, beneficio, provisao, encargo
    Column("tipo_calculo", String(60)),        # fixo, pct_salario, pct_sal_peri, qtd_x_sh, unitario_x_qtd, por_dependente
    Column("base_calculo", String(200)),       # descrição da base (ex: "salario + periculosidade")
    Column("percentual", Float, default=0.0),
    Column("valor_fixo", Float, default=0.0),
    Column("quantidade_padrao", Float, default=0.0),
    Column("incide_inss", Boolean, default=False),
    Column("incide_fgts", Boolean, default=False),
    Column("incide_ferias", Boolean, default=False),
    Column("incide_decimo", Boolean, default=False),
    Column("empresa_codigo", String(20)),      # NULL = todas
    Column("vinculo_codigo", String(40)),      # NULL = todos
    Column("cargo_grupo", String(80)),         # NULL = todos
    Column("prioridade", Integer, default=99),
    Column("status", String(20), default="Ativo"),
    Column("vigencia_inicio", String(10)),
    Column("vigencia_fim", String(10)),
    Column("criado_em", DateTime, default=datetime.utcnow),
    Column("criado_por", String(120)),
)

budget_beneficios = Table(
    "budget_beneficios", metadata_budget,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("codigo", String(20), nullable=False),
    Column("descricao", String(200), nullable=False),
    Column("empresa_codigo", String(20)),
    Column("vinculo_codigo", String(40)),
    Column("cargo_grupo", String(80)),
    Column("valor_fixo", Float, default=0.0),
    Column("valor_unitario", Float, default=0.0),
    Column("quantidade", Float, default=0.0),
    Column("por_dependente", Boolean, default=False),
    Column("pct_empresa", Float, default=1.0),  # 1 = 100% empresa
    Column("status", String(20), default="Ativo"),
    Column("vigencia_inicio", String(10)),
    Column("vigencia_fim", String(10)),
    Column("criado_em", DateTime, default=datetime.utcnow),
    Column("criado_por", String(120)),
)

budget_encargos = Table(
    "budget_encargos", metadata_budget,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("codigo", String(20), nullable=False),
    Column("descricao", String(200), nullable=False),
    Column("empresa_codigo", String(20)),
    Column("vinculo_codigo", String(40)),
    Column("percentual", Float, default=0.0),
    Column("divisor", Float, default=1.0),
    Column("verbas_base", Text),              # lista separada por vírgula de codigos de verba
    Column("prioridade", Integer, default=99),
    Column("status", String(20), default="Ativo"),
    Column("vigencia_inicio", String(10)),
    Column("vigencia_fim", String(10)),
    Column("criado_em", DateTime, default=datetime.utcnow),
    Column("criado_por", String(120)),
)

budget_excecoes = Table(
    "budget_excecoes", metadata_budget,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("empresa_codigo", String(20)),
    Column("matricula", String(40), nullable=False),
    Column("codigo_verba", String(20)),
    Column("descricao_verba", String(200)),
    Column("percentual", Float),
    Column("valor", Float),
    Column("quantidade", Float),
    Column("justificativa", Text),
    Column("prioridade", Integer, default=1),
    Column("status", String(20), default="Ativo"),
    Column("vigencia_inicio", String(10)),
    Column("vigencia_fim", String(10)),
    Column("criado_em", DateTime, default=datetime.utcnow),
    Column("criado_por", String(120)),
)

budget_quantidades = Table(
    "budget_quantidades", metadata_budget,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("cenario", String(60), default="Budget Original"),
    Column("competencia", String(10)),        # YYYY-MM
    Column("parametro", String(80), nullable=False),  # ex: "he_50", "he_100", "dias_vr", "noturno"
    Column("quantidade", Float, default=0.0),
    Column("empresa_codigo", String(20)),
    Column("matricula", String(40)),
    Column("codigo_cargo", String(40)),
    Column("cargo_grupo", String(80)),
    Column("centro_custo", String(30)),
    Column("status", String(20), default="Ativo"),
    Column("criado_em", DateTime, default=datetime.utcnow),
    Column("criado_por", String(120)),
)

budget_regras = Table(
    "budget_regras", metadata_budget,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("codigo", String(60), nullable=False),
    Column("descricao", String(200), nullable=False),
    Column("categoria", String(40)),
    Column("tipo_calculo", String(60), default="valor_fixo"),
    Column("valor", Float, default=0.0),
    Column("quantidade", Float, default=0.0),
    Column("percentual", Float, default=0.0),
    Column("aplicacao", String(30), default="calcular"),
    Column("matriculas", Text),
    Column("condicao_campo", String(40)),
    Column("condicao_operador", String(30)),
    Column("condicao_valor", Text),
    Column("condicoes_json", Text),
    Column("empresa_contem", String(120)),
    Column("nivel1", String(80)),
    Column("codigo_cargo", String(40)),
    Column("vinculo_codigo", String(40)),
    Column("prioridade", Integer, default=99),
    Column("status", String(20), default="Ativo"),
    Column("vigencia_inicio", String(10)),
    Column("vigencia_fim", String(10)),
    Column("criado_em", DateTime, default=datetime.utcnow),
    Column("criado_por", String(120)),
)

budget_cenarios = Table(
    "budget_cenarios", metadata_budget,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("nome", String(80), nullable=False, unique=True),
    Column("descricao", Text),
    Column("bloqueado", Boolean, default=False),  # Budget Original aprovado
    Column("ordem", Integer, default=99),
    Column("status", String(20), default="Ativo"),
    Column("criado_em", DateTime, default=datetime.utcnow),
    Column("criado_por", String(120)),
)

budget_resultado = Table(
    "budget_resultado", metadata_budget,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("cenario", String(80), nullable=False),
    Column("versao", Integer, default=1),
    Column("empresa_codigo", String(20)),
    Column("empresa_nome", String(255)),
    Column("cnpj", String(30)),
    Column("competencia", String(10)),
    Column("matricula", String(40)),
    Column("nome_empregado", String(200)),
    Column("codigo_cargo", String(40)),
    Column("cargo_nome", String(200)),
    Column("cargo_grupo", String(80)),
    Column("vinculo", String(80)),
    Column("centro_custo", String(30)),
    Column("codigo_verba", String(20)),
    Column("descricao_verba", String(200)),
    Column("categoria_verba", String(40)),
    Column("valor_realizado", Float),
    Column("valor_budget", Float),
    Column("origem_regra", String(200)),
    Column("id_parametro", Integer),
    Column("vigencia_usada", String(30)),
    Column("processado_em", DateTime, default=datetime.utcnow),
    Column("processado_por", String(120)),
)

metadata_budget.create_all(engine)

# Migração: adiciona colunas de vínculo ao budget_cargos se não existirem
try:
    with engine.connect() as _conn:
        dialect = engine.dialect.name  # "sqlite" ou "postgresql"
        if dialect == "sqlite":
            _cargos_novos_cols_sq = [
                ("tem_fgts", "BOOLEAN DEFAULT 1"),
                ("tem_inss", "BOOLEAN DEFAULT 1"),
                ("tem_d13", "BOOLEAN DEFAULT 1"),
                ("tem_ferias", "BOOLEAN DEFAULT 1"),
                ("tem_terca", "BOOLEAN DEFAULT 1"),
                ("tem_aviso", "BOOLEAN DEFAULT 1"),
                ("tem_plr", "BOOLEAN DEFAULT 0"),
                ("pode_he", "BOOLEAN DEFAULT 1"),
                ("pode_beneficios", "BOOLEAN DEFAULT 1"),
                ("competencia", "VARCHAR(20)"),
                ("matricula", "VARCHAR(40)"),
                ("nome", "VARCHAR(200)"),
                ("salario", "FLOAT DEFAULT 0"),
                ("horas_mes", "FLOAT DEFAULT 200"),
                ("dependentes", "INTEGER DEFAULT 0"),
                ("tem_periculosidade", "BOOLEAN DEFAULT 0"),
            ]
            _rows = _conn.execute(text("PRAGMA table_info(budget_cargos)")).fetchall()
            existing = [row[1] for row in _rows]
            for col, coldef in _cargos_novos_cols_sq:
                if col not in existing:
                    _conn.execute(text(f"ALTER TABLE budget_cargos ADD COLUMN {col} {coldef}"))
        else:
            # PostgreSQL: usa TRUE/FALSE para BOOLEAN
            _cargos_novos_cols_pg = [
                ("tem_fgts", "BOOLEAN DEFAULT TRUE"),
                ("tem_inss", "BOOLEAN DEFAULT TRUE"),
                ("tem_d13", "BOOLEAN DEFAULT TRUE"),
                ("tem_ferias", "BOOLEAN DEFAULT TRUE"),
                ("tem_terca", "BOOLEAN DEFAULT TRUE"),
                ("tem_aviso", "BOOLEAN DEFAULT TRUE"),
                ("tem_plr", "BOOLEAN DEFAULT FALSE"),
                ("pode_he", "BOOLEAN DEFAULT TRUE"),
                ("pode_beneficios", "BOOLEAN DEFAULT TRUE"),
                ("competencia", "VARCHAR(20)"),
                ("matricula", "VARCHAR(40)"),
                ("nome", "VARCHAR(200)"),
                ("salario", "FLOAT DEFAULT 0"),
                ("horas_mes", "FLOAT DEFAULT 200"),
                ("dependentes", "INTEGER DEFAULT 0"),
                ("tem_periculosidade", "BOOLEAN DEFAULT FALSE"),
            ]
            for col, coldef in _cargos_novos_cols_pg:
                _conn.execute(text(
                    f"ALTER TABLE budget_cargos ADD COLUMN IF NOT EXISTS {col} {coldef}"
                ))
        _conn.commit()
except Exception as _e:
    import logging
    logging.getLogger(__name__).warning(f"Migração budget_cargos: {_e}")

# Migração: periculosidade passa a ser padrão do cadastro de níveis de cargo
try:
    with engine.connect() as _conn:
        dialect = engine.dialect.name
        if dialect == "sqlite":
            _rows = _conn.execute(text("PRAGMA table_info(budget_cargos_niveis)")).fetchall()
            existing = [row[1] for row in _rows]
            if "tem_periculosidade" not in existing:
                _conn.execute(text("ALTER TABLE budget_cargos_niveis ADD COLUMN tem_periculosidade BOOLEAN DEFAULT 0"))
        else:
            _conn.execute(text(
                "ALTER TABLE budget_cargos_niveis ADD COLUMN IF NOT EXISTS tem_periculosidade BOOLEAN DEFAULT FALSE"
            ))
        try:
            _conn.execute(text("""
                UPDATE budget_cargos_niveis
                SET tem_periculosidade = 1
                WHERE cargo_normalizado IN (
                    SELECT DISTINCT UPPER(TRIM(REPLACE(REPLACE(REPLACE(ff.cargo, '.', ' '), '-', ' '), '/', ' ')))
                    FROM folha_funcionarios ff
                    JOIN folha_rubricas fr ON fr.id_funcionario = ff.id_funcionario
                    WHERE ff.cargo IS NOT NULL
                      AND ff.cargo != ''
                      AND UPPER(fr.descricao) LIKE '%PERICULOSIDADE%'
                )
            """))
        except Exception:
            pass
        _conn.commit()
except Exception as _e:
    import logging
    logging.getLogger(__name__).warning(f"Migração budget_cargos_niveis: {_e}")

# Migração: centraliza exceções por pessoa/lista na tabela de regras
try:
    with engine.connect() as _conn:
        dialect = engine.dialect.name
        if dialect == "sqlite":
            _rows = _conn.execute(text("PRAGMA table_info(budget_regras)")).fetchall()
            existing = [row[1] for row in _rows]
            for col, coldef in [
                ("aplicacao", "VARCHAR(30) DEFAULT 'calcular'"),
                ("matriculas", "TEXT"),
                ("condicao_campo", "VARCHAR(40)"),
                ("condicao_operador", "VARCHAR(30)"),
                ("condicao_valor", "TEXT"),
                ("condicoes_json", "TEXT"),
            ]:
                if col not in existing:
                    _conn.execute(text(f"ALTER TABLE budget_regras ADD COLUMN {col} {coldef}"))
        else:
            _conn.execute(text(
                "ALTER TABLE budget_regras ADD COLUMN IF NOT EXISTS aplicacao VARCHAR(30) DEFAULT 'calcular'"
            ))
            _conn.execute(text(
                "ALTER TABLE budget_regras ADD COLUMN IF NOT EXISTS matriculas TEXT"
            ))
            _conn.execute(text(
                "ALTER TABLE budget_regras ADD COLUMN IF NOT EXISTS condicao_campo VARCHAR(40)"
            ))
            _conn.execute(text(
                "ALTER TABLE budget_regras ADD COLUMN IF NOT EXISTS condicao_operador VARCHAR(30)"
            ))
            _conn.execute(text(
                "ALTER TABLE budget_regras ADD COLUMN IF NOT EXISTS condicao_valor TEXT"
            ))
            _conn.execute(text(
                "ALTER TABLE budget_regras ADD COLUMN IF NOT EXISTS condicoes_json TEXT"
            ))
        _conn.execute(text("UPDATE budget_regras SET aplicacao = 'calcular' WHERE aplicacao IS NULL OR aplicacao = ''"))
        _conn.commit()
except Exception as _e:
    import logging
    logging.getLogger(__name__).warning(f"Migração budget_regras: {_e}")

# Cenários padrão
def _seed_cenarios(db: Session):
    existentes = db.execute(select(budget_cenarios.c.nome)).scalars().all()
    padroes = [
        ("Budget Original", "Orçamento aprovado — somente leitura após aprovação", True, 1),
        ("Budget Revisado", "Revisão do orçamento original", False, 2),
        ("Forecast", "Projeção atualizada do ano", False, 3),
        ("Simulação", "Simulações e cenários hipotéticos", False, 4),
        ("Realizado", "Valores realizados importados da folha", False, 5),
    ]
    for nome, desc, bloqueado, ordem in padroes:
        if nome not in existentes:
            db.execute(insert(budget_cenarios).values(
                nome=nome, descricao=desc, bloqueado=bloqueado, ordem=ordem
            ))
    db.commit()


def _seed_regras_budget(db: Session):
    existentes = {
        (
            r["codigo"],
            r.get("empresa_contem") or "",
            r.get("nivel1") or "",
            r.get("codigo_cargo") or "",
            r.get("matriculas") or "",
            r.get("vigencia_inicio") or "",
            r.get("vigencia_fim") or "",
        )
        for r in db.execute(select(budget_regras)).mappings().all()
    }
    regras = [
        # Quantidades pré-assinaladas
        dict(codigo="QTD_HE50", descricao="Quantidade padrão HE 50%", categoria="quantidade", tipo_calculo="quantidade", quantidade=1.0),
        dict(codigo="QTD_HE100", descricao="Quantidade padrão HE 100%", categoria="quantidade", tipo_calculo="quantidade", quantidade=0.0),
        dict(codigo="QTD_NOTURNO", descricao="Quantidade padrão adicional noturno", categoria="quantidade", tipo_calculo="quantidade", quantidade=3.0),
        dict(codigo="QTD_HE25", descricao="Quantidade padrão HE sobre 25%", categoria="quantidade", tipo_calculo="quantidade", quantidade=10.0),
        dict(codigo="QTD_DIAS_VR", descricao="Dias padrão de vale refeição", categoria="quantidade", tipo_calculo="quantidade", quantidade=22.0),

        # Adicionais e horas extras
        dict(codigo="PERI", descricao="Periculosidade", categoria="adicional", tipo_calculo="percentual", percentual=0.30),
        dict(codigo="ADIC25", descricao="Adicional 25%", categoria="adicional", tipo_calculo="percentual", percentual=0.25),
        dict(codigo="NOTURNO", descricao="Adicional Noturno", categoria="adicional", tipo_calculo="percentual", percentual=0.35),
        dict(codigo="HE25", descricao="HE sobre Adicional 25%", categoria="he", tipo_calculo="percentual", percentual=0.25),
        dict(codigo="HE50", descricao="Hora Extra 50%", categoria="he", tipo_calculo="percentual", percentual=1.50),
        dict(codigo="HE100", descricao="Hora Extra 100%", categoria="he", tipo_calculo="percentual", percentual=2.00),
        dict(codigo="PREMIO_PIRES", descricao="Prêmio PIRES", categoria="adicional", tipo_calculo="percentual", percentual=0.20, empresa_contem="PIRES", prioridade=20),

        # Benefícios fixos
        dict(codigo="VR_DIA", descricao="Vale Refeição - valor diário", categoria="beneficio", tipo_calculo="unitario_x_qtd", valor=38.0),
        dict(codigo="VA", descricao="Vale Alimentação", categoria="beneficio", tipo_calculo="valor_fixo", valor=313.0),
        dict(codigo="COMB", descricao="Vale Combustível", categoria="beneficio", tipo_calculo="valor_fixo", valor=397.75),
        dict(codigo="ACADEMIA", descricao="Academia", categoria="beneficio", tipo_calculo="valor_fixo", valor=53.0),
        dict(codigo="ODONTO", descricao="Assistência Odontológica por vida", categoria="beneficio", tipo_calculo="por_dependente", valor=11.24),

        # Saúde por nível
        dict(codigo="SAUDE", descricao="Assistência Médica - Diretor", categoria="beneficio", tipo_calculo="por_dependente", valor=2423.38, nivel1="Diretor", prioridade=10),
        dict(codigo="SAUDE", descricao="Assistência Médica - Gerente", categoria="beneficio", tipo_calculo="por_dependente", valor=1873.31, nivel1="Gerente", prioridade=20),
        dict(codigo="SAUDE", descricao="Assistência Médica - Supervisor", categoria="beneficio", tipo_calculo="por_dependente", valor=748.86, nivel1="Supervisor", prioridade=30),
        dict(codigo="SAUDE", descricao="Assistência Médica - Coordenadores", categoria="beneficio", tipo_calculo="por_dependente", valor=748.86, nivel1="Coordenadores", prioridade=31),
        dict(codigo="SAUDE", descricao="Assistência Médica - Geral", categoria="beneficio", tipo_calculo="por_dependente", valor=615.55, prioridade=99),

        # Seguro por empresa e nível
        dict(codigo="SEGURO_VIDA", descricao="Seguro de Vida DENER - Diretor", categoria="beneficio", tipo_calculo="valor_fixo", valor=52.18, empresa_contem="DENER", nivel1="Diretor", prioridade=10),
        dict(codigo="SEGURO_VIDA", descricao="Seguro de Vida DENER - Geral", categoria="beneficio", tipo_calculo="valor_fixo", valor=13.04, empresa_contem="DENER", prioridade=20),
        dict(codigo="SEGURO_VIDA", descricao="Seguro de Vida GT3 - Diretor", categoria="beneficio", tipo_calculo="valor_fixo", valor=56.86, empresa_contem="GT3", nivel1="Diretor", prioridade=10),
        dict(codigo="SEGURO_VIDA", descricao="Seguro de Vida GT3 - Geral", categoria="beneficio", tipo_calculo="valor_fixo", valor=20.39, empresa_contem="GT3", prioridade=20),
        dict(codigo="SEGURO_VIDA", descricao="Seguro de Vida PIRES - Diretor", categoria="beneficio", tipo_calculo="valor_fixo", valor=0.0, empresa_contem="PIRES", nivel1="Diretor", prioridade=10),
        dict(codigo="SEGURO_VIDA", descricao="Seguro de Vida PIRES - Geral", categoria="beneficio", tipo_calculo="valor_fixo", valor=7.39, empresa_contem="PIRES", prioridade=20),

        # Provisões e encargos
        dict(codigo="PROV_FER", descricao="Provisão Férias", categoria="provisao", tipo_calculo="percentual", percentual=1 / 12),
        dict(codigo="PROV_1T", descricao="Provisão 1/3 Férias", categoria="provisao", tipo_calculo="percentual", percentual=1 / 36),
        dict(codigo="PROV_13", descricao="Provisão 13º Salário", categoria="provisao", tipo_calculo="percentual", percentual=1 / 12),
        dict(codigo="PROV_AVI", descricao="Provisão Aviso Prévio", categoria="provisao", tipo_calculo="percentual", percentual=1 / 12),
        dict(codigo="PROV_PLR", descricao="Provisão PLR", categoria="provisao", tipo_calculo="percentual", percentual=1 / 12),
        dict(codigo="FGTS", descricao="FGTS", categoria="encargo", tipo_calculo="percentual", percentual=0.08),
        dict(codigo="INSS_PAT", descricao="INSS Patronal", categoria="encargo", tipo_calculo="percentual", percentual=0.268),
    ]
    for regra in regras:
        chave = (
            regra["codigo"],
            regra.get("empresa_contem") or "",
            regra.get("nivel1") or "",
            regra.get("codigo_cargo") or "",
            regra.get("matriculas") or "",
            regra.get("vigencia_inicio") or "2000-01-01",
            regra.get("vigencia_fim") or "",
        )
        if chave in existentes:
            continue
        regra.setdefault("valor", 0.0)
        regra.setdefault("quantidade", 0.0)
        regra.setdefault("percentual", 0.0)
        regra.setdefault("aplicacao", "calcular")
        regra.setdefault("matriculas", None)
        regra.setdefault("prioridade", 99)
        regra.setdefault("status", "Ativo")
        regra.setdefault("vigencia_inicio", "2000-01-01")
        regra.setdefault("criado_por", "seed")
        db.execute(insert(budget_regras).values(**regra))
    db.execute(delete(budget_regras).where(
        budget_regras.c.codigo == "APOIO_ETAPA",
        budget_regras.c.criado_por == "seed",
    ))
    db.commit()


def _seed_cargos_niveis(db: Session):
    existentes = set(db.execute(
        select(budget_cargos_niveis.c.cargo_normalizado)
    ).scalars().all())
    for cargo_norm, cfg in CARGOS_PADRAO.items():
        if cargo_norm in existentes:
            continue
        db.execute(insert(budget_cargos_niveis).values(
            cargo=cfg.get("cargo_original") or cargo_norm,
            cargo_normalizado=cargo_norm,
            nivel1=cfg.get("nivel1") or "",
            nivel2=cfg.get("nivel2") or "",
            nivel3=cfg.get("nivel3") or "",
            tem_periculosidade=bool(cfg.get("tem_periculosidade")),
            bate_ponto=bool(cfg.get("bate_ponto")),
            pct_adicional_25=float(cfg.get("pct_adicional_25") or 0),
            pct_he_sobre_25=float(cfg.get("pct_he_sobre_25") or 0),
            pode_he=bool(cfg.get("pode_he")),
            status="Ativo",
            criado_por="seed",
        ))
    db.commit()

try:
    from app.database import SessionLocal
    _db = SessionLocal()
    _seed_cenarios(_db)
    _seed_regras_budget(_db)
    _seed_cargos_niveis(_db)
    _db.close()
except Exception:
    pass


# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

def _usuario(request: Request) -> str:
    u = getattr(request.state, "current_user", None) or {}
    return u.get("nome") or u.get("email") or "sistema"


def _fechar_vigencia(db: Session, table, id_ant: int) -> None:
    """Fecha vigência do registro anterior com vigencia_fim = ontem."""
    from datetime import timedelta
    ontem = (date.today() - timedelta(days=1)).isoformat()
    db.execute(update(table).where(table.c.id == id_ant).values(vigencia_fim=ontem))


def _inicio_competencia(valor: str | None) -> str:
    comp = _competencia_chave(valor)
    if re.match(r"^\d{4}-\d{2}$", comp):
        return f"{comp}-01"
    return date.today().replace(day=1).isoformat()


def _fim_mes_anterior(inicio_iso: str) -> str:
    from datetime import timedelta
    inicio = datetime.strptime(inicio_iso, "%Y-%m-%d").date()
    return (inicio - timedelta(days=1)).isoformat()


def _fechar_regras_abertas_anteriores(db: Session, codigo: str, inicio_iso: str, excluir_id: int | None = None) -> None:
    fim = _fim_mes_anterior(inicio_iso)
    q = (
        update(budget_regras)
        .where(budget_regras.c.codigo == codigo)
        .where((budget_regras.c.vigencia_fim.is_(None)) | (budget_regras.c.vigencia_fim == ""))
        .where(budget_regras.c.vigencia_inicio < inicio_iso)
        .values(vigencia_fim=fim)
    )
    if excluir_id:
        q = q.where(budget_regras.c.id != excluir_id)
    db.execute(q)


def _fmt_data_br(valor: str | None) -> str:
    texto = str(valor or "").strip()
    if not texto:
        return ""
    try:
        return datetime.strptime(texto[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except Exception:
        return texto


def _competencia_chave(valor: str | None) -> str:
    texto = str(valor or "").strip()
    m = re.match(r"^(\d{2})/(\d{4})$", texto)
    if m:
        return f"{m.group(2)}-{m.group(1)}"
    return texto[:7]


def _vigente(row, competencia: str) -> bool:
    """Verifica se um registro está vigente para a competência (YYYY-MM)."""
    comp = _competencia_chave(competencia)
    inicio = _competencia_chave(row.get("vigencia_inicio"))
    fim = _competencia_chave(row.get("vigencia_fim"))
    if inicio and comp < inicio:
        return False
    if fim and comp > fim:
        return False
    return True


def _status_vigencia_regra(row, hoje: date | None = None) -> str:
    hoje = hoje or date.today()
    inicio_txt = str(row.get("vigencia_inicio") or "").strip()
    fim_txt = str(row.get("vigencia_fim") or "").strip()
    try:
        inicio = datetime.strptime(inicio_txt[:10], "%Y-%m-%d").date() if inicio_txt else None
    except Exception:
        inicio = None
    try:
        fim = datetime.strptime(fim_txt[:10], "%Y-%m-%d").date() if fim_txt else None
    except Exception:
        fim = None

    if fim and fim < hoje:
        return "encerrada"
    if str(row.get("status") or "") == "Ativo" and (not inicio or inicio <= hoje) and (not fim or hoje <= fim):
        return "vigente"
    if str(row.get("status") or "") == "Ativo":
        return "ativa"
    return "inativa"


def _fmt_vigencia_regra(row) -> str:
    inicio = _fmt_data_br(row.get("vigencia_inicio"))
    fim = _fmt_data_br(row.get("vigencia_fim"))
    if inicio and fim:
        return f"{inicio} até {fim}"
    return inicio or fim or ""


def _buscar_verba_vigente(db: Session, codigo: str, competencia: str):
    rows = db.execute(
        select(budget_verbas)
        .where(budget_verbas.c.codigo == codigo)
        .where(budget_verbas.c.status == "Ativo")
        .order_by(budget_verbas.c.prioridade)
    ).mappings().all()
    return next((r for r in rows if _vigente(r, competencia)), None)


def _buscar_beneficio(db: Session, codigo: str, competencia: str,
                      empresa: str = "", vinculo: str = "", grupo: str = ""):
    rows = db.execute(
        select(budget_beneficios)
        .where(budget_beneficios.c.codigo == codigo)
        .where(budget_beneficios.c.status == "Ativo")
    ).mappings().all()
    vigentes = [r for r in rows if _vigente(r, competencia)]
    # Prioridade: empresa+grupo > empresa > grupo > geral
    for r in vigentes:
        if r["empresa_codigo"] == empresa and r["cargo_grupo"] == grupo:
            return r
    for r in vigentes:
        if r["empresa_codigo"] == empresa:
            return r
    for r in vigentes:
        if r["cargo_grupo"] == grupo:
            return r
    return vigentes[0] if vigentes else None


def _buscar_excecao(db: Session, matricula: str, codigo_verba: str,
                    empresa: str, competencia: str):
    rows = db.execute(
        select(budget_excecoes)
        .where(budget_excecoes.c.matricula == matricula)
        .where(budget_excecoes.c.codigo_verba == codigo_verba)
        .where(budget_excecoes.c.status == "Ativo")
        .order_by(budget_excecoes.c.prioridade)
    ).mappings().all()
    vigentes = [r for r in rows if _vigente(r, competencia)]
    for r in vigentes:
        if r["empresa_codigo"] == empresa:
            return r
    return vigentes[0] if vigentes else None


def _buscar_quantidade(db: Session, parametro: str, competencia: str, cenario: str,
                       empresa: str = "", matricula: str = "",
                       codigo_cargo: str = "", grupo: str = "", cc: str = "") -> float:
    rows = db.execute(
        select(budget_quantidades)
        .where(budget_quantidades.c.parametro == parametro)
        .where(budget_quantidades.c.competencia == competencia)
        .where(budget_quantidades.c.cenario == cenario)
        .where(budget_quantidades.c.status == "Ativo")
    ).mappings().all()
    # Prioridade: matrícula > cargo > grupo > cc > empresa > geral
    for filtro in [
        lambda r: r["matricula"] == matricula and matricula,
        lambda r: r["codigo_cargo"] == codigo_cargo and codigo_cargo,
        lambda r: r["cargo_grupo"] == grupo and grupo,
        lambda r: r["centro_custo"] == cc and cc,
        lambda r: r["empresa_codigo"] == empresa and empresa,
        lambda r: not r["matricula"] and not r["codigo_cargo"] and not r["cargo_grupo"],
    ]:
        match = next((r for r in rows if filtro(r)), None)
        if match:
            return float(match["quantidade"] or 0)
    return 0.0


def _buscar_encargo(db: Session, codigo: str, competencia: str,
                    empresa: str, vinculo: str):
    rows = db.execute(
        select(budget_encargos)
        .where(budget_encargos.c.codigo == codigo)
        .where(budget_encargos.c.status == "Ativo")
        .order_by(budget_encargos.c.prioridade)
    ).mappings().all()
    vigentes = [r for r in rows if _vigente(r, competencia)]
    for r in vigentes:
        if r["empresa_codigo"] == empresa and r["vinculo_codigo"] == vinculo:
            return r
    for r in vigentes:
        if r["empresa_codigo"] == empresa:
            return r
    for r in vigentes:
        if r["vinculo_codigo"] == vinculo:
            return r
    return vigentes[0] if vigentes else None


def _buscar_vinculo(db: Session, codigo: str, competencia: str):
    rows = db.execute(
        select(budget_vinculos)
        .where(budget_vinculos.c.codigo == codigo)
        .where(budget_vinculos.c.status == "Ativo")
    ).mappings().all()
    return next((r for r in rows if _vigente(r, competencia)), None)


def _buscar_cargo(db: Session, codigo_cargo: str, competencia: str):
    rows = db.execute(
        select(budget_cargos)
        .where(budget_cargos.c.codigo_cargo == codigo_cargo)
        .where(budget_cargos.c.status == "Ativo")
    ).mappings().all()
    return next((r for r in rows if _vigente(r, competencia)), None)


def _buscar_cargo_empregado(db: Session, matricula: str, codigo_cargo: str, competencia: str):
    rows = db.execute(
        select(budget_cargos)
        .where(budget_cargos.c.status == "Ativo")
    ).mappings().all()
    for r in rows:
        if r["matricula"] == matricula and r["competencia"] == competencia:
            return r
    for r in rows:
        if r["codigo_cargo"] == codigo_cargo and _vigente(r, competencia):
            return r
    return None


def _buscar_nivel_cargo(db: Session, cargo: str | None):
    cargo_norm = _normalizar_cargo(cargo)
    if not cargo_norm:
        return None
    row = db.execute(
        select(budget_cargos_niveis)
        .where(budget_cargos_niveis.c.cargo_normalizado == cargo_norm)
        .where(budget_cargos_niveis.c.status == "Ativo")
    ).mappings().first()
    if row:
        return dict(row)
    return None


def _empresa_contem(empresa: str, termo: str) -> bool:
    return _normalizar_cargo(termo) in _normalizar_cargo(empresa)


def _regra_contem_matricula(lista: str | None, matricula: str) -> bool:
    if not lista:
        return True
    alvo = str(matricula or "").strip()
    if not alvo:
        return False
    itens = [item.strip() for item in re.split(r"[,;\n]+", str(lista)) if item.strip()]
    return alvo in itens


def _avaliar_condicao(campo: str, operador: str, valor: str, contexto: dict[str, str]) -> bool:
    aliases = {
        "matricula": "matricula",
        "nome": "nome",
        "cargo": "cargo",
        "cargo nome": "cargo",
        "nivel1": "nivel1",
        "nivel": "nivel1",
        "empresa": "empresa",
        "vinculo": "vinculo",
        "codigo cargo": "codigo_cargo",
        "centro custo": "centro_custo",
    }
    chave = aliases.get(_normalizar_cargo(campo).lower(), campo)
    atual = str(contexto.get(chave) or "")
    atual_norm = _normalizar_cargo(atual)
    valor_norm = _normalizar_cargo(valor)
    op = _normalizar_cargo(operador).lower().replace(" ", "_")

    if op in {"contem", "contém"}:
        return valor_norm in atual_norm
    if op in {"nao_contem", "não_contém", "nao_contem"}:
        return valor_norm not in atual_norm
    if op in {"igual", "e", "é"}:
        return atual_norm == valor_norm
    if op in {"diferente", "nao_e", "não_é"}:
        return atual_norm != valor_norm
    return valor_norm in atual_norm


def _condicoes_da_regra(row) -> list[dict[str, str]]:
    raw = str(row.get("condicoes_json") or "").strip()
    if raw:
        try:
            condicoes = json.loads(raw)
            if isinstance(condicoes, list):
                return [
                    {
                        "campo": str(c.get("campo") or "").strip(),
                        "operador": str(c.get("operador") or "contem").strip(),
                        "valor": str(c.get("valor") or "").strip(),
                    }
                    for c in condicoes
                    if isinstance(c, dict) and str(c.get("campo") or "").strip() and str(c.get("valor") or "").strip()
                ]
        except Exception:
            pass
    campo = str(row.get("condicao_campo") or "").strip()
    valor = str(row.get("condicao_valor") or "").strip()
    if campo and valor:
        return [{
            "campo": campo,
            "operador": str(row.get("condicao_operador") or "contem").strip(),
            "valor": valor,
        }]
    return []


def _resumo_condicoes(row) -> str:
    condicoes = _condicoes_da_regra(row)
    if not condicoes:
        return ""
    partes = [f"{c['campo']} {c.get('operador') or 'contem'} {c['valor']}" for c in condicoes[:3]]
    if len(condicoes) > 3:
        partes.append(f"+{len(condicoes) - 3}")
    return " ou ".join(partes)


def _detalhes_excecoes_regra(row) -> list[str]:
    detalhes: list[str] = []
    aplicacao = row.get("aplicacao") or "calcular"
    if aplicacao == "nao_recebe":
        detalhes.append("Aplicação: não recebe / bloqueia cálculo")
    elif aplicacao == "somente_recebe":
        detalhes.append("Aplicação: somente recebe quando a exceção bater")

    matriculas = str(row.get("matriculas") or "").strip()
    if matriculas:
        detalhes.append(f"Matrículas: {matriculas}")

    for condicao in _condicoes_da_regra(row):
        campo = condicao.get("campo") or "campo"
        operador = condicao.get("operador") or "contem"
        valor = condicao.get("valor") or ""
        detalhes.append(f"Condição: {campo} {operador} {valor}")

    filtros = [
        ("Empresa contém", row.get("empresa_contem")),
        ("Nível", row.get("nivel1")),
        ("Código cargo", row.get("codigo_cargo")),
        ("Vínculo", row.get("vinculo_codigo")),
    ]
    for rotulo, valor in filtros:
        valor_txt = str(valor or "").strip()
        if valor_txt:
            detalhes.append(f"{rotulo}: {valor_txt}")

    return detalhes


def _regra_modal_payload(row) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "codigo": row.get("codigo"),
        "descricao": row.get("descricao"),
        "categoria": row.get("categoria") or "",
        "tipo": row.get("tipo_calculo") or "valor_fixo",
        "valor": row.get("valor") or 0,
        "quantidade": row.get("quantidade") or 0,
        "percentual": row.get("percentual") or 0,
        "aplicacao": row.get("aplicacao") or "calcular",
        "matriculas": row.get("matriculas") or "",
        "condicao_campo": row.get("condicao_campo") or "",
        "condicao_operador": row.get("condicao_operador") or "contem",
        "condicao_valor": row.get("condicao_valor") or "",
        "condicoes_json": row.get("condicoes_json") or "",
        "empresa": row.get("empresa_contem") or "",
        "nivel1": row.get("nivel1") or "",
        "cargo": row.get("codigo_cargo") or "",
        "vinculo": row.get("vinculo_codigo") or "",
        "prioridade": row.get("prioridade") or 99,
        "status": row.get("status") or "Ativo",
    }


def _regra_tem_recorte(row) -> bool:
    return bool(
        _condicoes_da_regra(row)
        or str(row.get("matriculas") or "").strip()
        or str(row.get("empresa_contem") or "").strip()
        or str(row.get("nivel1") or "").strip()
        or str(row.get("codigo_cargo") or "").strip()
        or str(row.get("vinculo_codigo") or "").strip()
        or (row.get("aplicacao") or "calcular") != "calcular"
    )


def _condicao_regra_ok(row, contexto: dict[str, str]) -> bool:
    condicoes = _condicoes_da_regra(row)
    if not condicoes:
        return True
    return any(
        _avaliar_condicao(c["campo"], c.get("operador") or "contem", c["valor"], contexto)
        for c in condicoes
    )


def _buscar_regra_budget(db: Session, codigo: str, competencia: str,
                         empresa_nome: str = "", nivel1: str = "",
                         codigo_cargo: str = "", vinculo: str = "",
                         matricula: str = "", nome: str = "",
                         cargo_nome: str = "", centro_custo: str = ""):
    rows = db.execute(
        select(budget_regras)
        .where(budget_regras.c.codigo == codigo)
        .where(budget_regras.c.status == "Ativo")
        .order_by(budget_regras.c.prioridade)
    ).mappings().all()
    contexto = {
        "matricula": matricula,
        "nome": nome,
        "cargo": cargo_nome,
        "nivel1": nivel1,
        "empresa": empresa_nome,
        "vinculo": vinculo,
        "codigo_cargo": codigo_cargo,
        "centro_custo": centro_custo,
    }
    matches = []
    only_matches = []
    tem_somente_recebe = False
    for row in rows:
        if not _vigente(row, competencia):
            continue
        if row.get("empresa_contem") and not _empresa_contem(empresa_nome, row["empresa_contem"]):
            continue
        if row.get("nivel1") and _normalizar_cargo(row["nivel1"]) != _normalizar_cargo(nivel1):
            continue
        if row.get("codigo_cargo") and row["codigo_cargo"] != codigo_cargo:
            continue
        if row.get("vinculo_codigo") and row["vinculo_codigo"] != vinculo:
            continue
        somente_recebe = (row.get("aplicacao") or "calcular") == "somente_recebe"
        if somente_recebe:
            tem_somente_recebe = True
        if row.get("matriculas") and not _regra_contem_matricula(row["matriculas"], matricula):
            continue
        if not _condicao_regra_ok(row, contexto):
            continue
        if somente_recebe:
            only_matches.append(row)
        else:
            matches.append(row)
    if only_matches:
        return only_matches[0]
    if tem_somente_recebe:
        return {
            "id": "somente_recebe",
            "codigo": codigo,
            "descricao": "Bloqueado por regra somente recebe",
            "aplicacao": "nao_recebe",
            "valor": 0.0,
            "quantidade": 0.0,
            "percentual": 0.0,
        }
    if matches:
        return matches[0]
    return None


def _regra_quantidade(db: Session, codigo: str, competencia: str, fallback: float,
                      empresa_nome: str = "", nivel1: str = "",
                      codigo_cargo: str = "", vinculo: str = "",
                      matricula: str = "", nome: str = "",
                      cargo_nome: str = "", centro_custo: str = "") -> float:
    regra = _buscar_regra_budget(db, codigo, competencia, empresa_nome, nivel1, codigo_cargo, vinculo, matricula, nome, cargo_nome, centro_custo)
    if regra and regra.get("quantidade") is not None:
        return float(regra.get("quantidade") or 0)
    return fallback


def _regra_valor(db: Session, codigo: str, competencia: str, fallback: float,
                 empresa_nome: str = "", nivel1: str = "",
                 codigo_cargo: str = "", vinculo: str = "",
                 matricula: str = "", nome: str = "",
                 cargo_nome: str = "", centro_custo: str = "") -> tuple[float, str]:
    regra = _buscar_regra_budget(db, codigo, competencia, empresa_nome, nivel1, codigo_cargo, vinculo, matricula, nome, cargo_nome, centro_custo)
    if regra:
        return float(regra.get("valor") or 0), f"Regra #{regra['id']}"
    return fallback, "Padrão"


def _regra_percentual(db: Session, codigo: str, competencia: str, fallback: float,
                      empresa_nome: str = "", nivel1: str = "",
                      codigo_cargo: str = "", vinculo: str = "",
                      matricula: str = "", nome: str = "",
                      cargo_nome: str = "", centro_custo: str = "") -> tuple[float, str]:
    regra = _buscar_regra_budget(db, codigo, competencia, empresa_nome, nivel1, codigo_cargo, vinculo, matricula, nome, cargo_nome, centro_custo)
    if regra and regra.get("percentual") is not None:
        return float(regra.get("percentual") or 0), f"Regra #{regra['id']}"
    return fallback, "Padrão"


def _regra_bloqueia(db: Session, codigo: str, competencia: str,
                    empresa_nome: str = "", nivel1: str = "",
                    codigo_cargo: str = "", vinculo: str = "",
                    matricula: str = "", nome: str = "",
                    cargo_nome: str = "", centro_custo: str = "") -> tuple[bool, str]:
    regra = _buscar_regra_budget(db, codigo, competencia, empresa_nome, nivel1, codigo_cargo, vinculo, matricula, nome, cargo_nome, centro_custo)
    if regra and (regra.get("aplicacao") or "calcular") == "nao_recebe":
        return True, f"Regra #{regra['id']}: não recebe"
    return False, ""


def _fmt_moeda(valor: float | int | None) -> str:
    texto = f"{float(valor or 0):,.2f}"
    return "R$ " + texto.replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt_num(valor: float | int | None, casas: int = 4) -> str:
    texto = f"{float(valor or 0):.{casas}f}".rstrip("0").rstrip(".")
    return texto.replace(".", ",") or "0"


def _fmt_pct(valor: float | int | None) -> str:
    texto = f"{float(valor or 0) * 100:.2f}".replace(".", ",")
    return texto.removesuffix(",00") + "%"


def _fmt_pct_input(valor: float | int | None) -> str:
    numero = float(valor or 0) * 100
    if abs(numero - round(numero)) < 0.000001:
        return str(int(round(numero)))
    return f"{numero:.4f}".rstrip("0").rstrip(".")


def _parse_pct_form(valor: Any) -> float:
    texto = str(valor or "").strip().replace("%", "").replace(",", ".")
    if not texto:
        return 0.0
    numero = float(texto)
    if numero == 0:
        return 0.0
    if re.match(r"^-?0\.", texto):
        return numero
    return numero / 100


def _quantidades_padrao(cargo_info: dict[str, Any] | None, cargo_nome: str = "") -> dict[str, float]:
    padrao = _parametros_padrao_cargo((cargo_info or {}).get("descricao") or cargo_nome)
    nivel1 = padrao.get("nivel1") or ""
    estagiario = _normalizar_cargo(nivel1) == "ESTAGIARIO"
    bate_ponto = bool((cargo_info or {}).get("bate_ponto", padrao["bate_ponto"]))
    pode_he = bool((cargo_info or {}).get("pode_he", padrao["pode_he"]))
    pct_he25 = float((cargo_info or {}).get("pct_he_sobre_25") or padrao["pct_he_sobre_25"] or 0)
    habilita_he = bate_ponto and pode_he and not estagiario
    return {
        "he_50": 1.0 if habilita_he else 0.0,
        "he_100": 0.0,
        "noturno": 3.0 if habilita_he else 0.0,
        "he_sobre_25": 10.0 if habilita_he and pct_he25 > 0 else 0.0,
        "dias_vr": 22.0,
    }


# ─────────────────────────────────────────────────────────────
# MOTOR DE CÁLCULO
# ─────────────────────────────────────────────────────────────

def _processar_empregado(db: Session, funcionario: dict, rubricas: list[dict],
                          competencia: str, cenario: str, usuario: str) -> list[dict]:
    """Calcula todas as verbas de budget para um empregado/competência/cenário."""
    matricula = funcionario.get("matricula") or ""
    nome = funcionario.get("nome") or ""
    empresa_codigo = funcionario.get("empresa_codigo") or ""
    empresa_nome = funcionario.get("empresa_nome") or ""
    cnpj = funcionario.get("cnpj") or ""
    vinculo = funcionario.get("vinculo") or ""
    cc = funcionario.get("centro_custo") or ""
    codigo_cargo = funcionario.get("codigo_cargo") or ""
    cargo_nome = funcionario.get("cargo") or ""
    salario = float(funcionario.get("salario") or 0)
    horas_mes = float(funcionario.get("horas_mes") or 220)
    dependentes = int(funcionario.get("nd") or 0)

    # Periculosidade: busca primeiro exceção, depois verba parametrizada
    peri_realizada = next(
        (float(r.get("valor") or 0) for r in rubricas
         if "PERICULOSIDADE" in str(r.get("descricao") or "").upper()),
        0.0
    )
    # Cargo e vínculo do cadastro
    cargo_bd = _buscar_cargo_empregado(db, matricula, codigo_cargo, competencia)
    cargo_base = (cargo_bd["descricao"] if cargo_bd else cargo_nome) or cargo_nome
    padrao_cargo = _buscar_nivel_cargo(db, cargo_base) or _parametros_padrao_cargo(cargo_base)
    tem_peri = bool(padrao_cargo.get("tem_periculosidade"))
    nivel1 = padrao_cargo["nivel1"]
    nivel2 = padrao_cargo["nivel2"]
    nivel3 = padrao_cargo["nivel3"]
    grupo = nivel1 or (cargo_bd["descricao"] if cargo_bd else "") or cargo_nome
    estagiario = _normalizar_cargo(nivel1) == "ESTAGIARIO"
    vinculo_bd = _buscar_vinculo(db, vinculo, competencia)

    resultados: list[dict] = []

    def linha(codigo: str, descricao: str, categoria: str,
              valor_real: float | None, valor_budget: float,
              origem: str, id_param: int | None = None, vig: str = ""):
        resultados.append({
            "cenario": cenario,
            "versao": 1,
            "empresa_codigo": empresa_codigo,
            "empresa_nome": empresa_nome,
            "cnpj": cnpj,
            "competencia": competencia,
            "matricula": matricula,
            "nome_empregado": nome,
            "codigo_cargo": codigo_cargo,
            "cargo_nome": cargo_nome,
            "cargo_grupo": grupo,
            "vinculo": vinculo,
            "centro_custo": cc,
            "codigo_verba": codigo,
            "descricao_verba": descricao,
            "categoria_verba": categoria,
            "valor_realizado": valor_real,
            "valor_budget": round(valor_budget, 2),
            "origem_regra": origem,
            "id_parametro": id_param,
            "vigencia_usada": vig,
            "processado_em": datetime.utcnow(),
            "processado_por": usuario,
        })

    def bloqueado(codigo: str) -> tuple[bool, str]:
        return _regra_bloqueia(
            db, codigo, competencia, empresa_nome, nivel1, codigo_cargo, vinculo, matricula, nome, cargo_nome, cc
        )

    def regra_quantidade(codigo: str, fallback: float) -> float:
        return _regra_quantidade(
            db, codigo, competencia, fallback, empresa_nome, nivel1, codigo_cargo, vinculo, matricula, nome, cargo_nome, cc
        )

    def regra_valor(codigo: str, fallback: float) -> tuple[float, str]:
        return _regra_valor(
            db, codigo, competencia, fallback, empresa_nome, nivel1, codigo_cargo, vinculo, matricula, nome, cargo_nome, cc
        )

    def regra_percentual(codigo: str, fallback: float) -> tuple[float, str]:
        return _regra_percentual(
            db, codigo, competencia, fallback, empresa_nome, nivel1, codigo_cargo, vinculo, matricula, nome, cargo_nome, cc
        )

    def buscar_regra(codigo: str):
        return _buscar_regra_budget(
            db, codigo, competencia, empresa_nome, nivel1, codigo_cargo, vinculo, matricula, nome, cargo_nome, cc
        )

    # ── SALÁRIO ──────────────────────────────────────────────
    linha("SAL", "Salário", "remuneracao", salario, salario,
          f"Folha: salário = {_fmt_moeda(salario)}")

    # ── PERICULOSIDADE ────────────────────────────────────────
    peri_bloqueado, _ = bloqueado("PERI")
    if tem_peri and not peri_bloqueado:
        exc = _buscar_excecao(db, matricula, "PERI", empresa_codigo, competencia)
        verba_peri = _buscar_verba_vigente(db, "PERI", competencia)
        if exc and exc.get("percentual") is not None:
            pct = float(exc["percentual"])
            peri_budget = salario * pct
            origem = f"Exceção #{exc['id']}: {_fmt_moeda(salario)} x {_fmt_pct(pct)} = {_fmt_moeda(peri_budget)}"
        elif buscar_regra("PERI"):
            pct, fonte = regra_percentual("PERI", 0.30)
            peri_budget = salario * pct
            origem = f"{fonte}: {_fmt_moeda(salario)} x {_fmt_pct(pct)} = {_fmt_moeda(peri_budget)}"
            vig = ""
        elif verba_peri:
            pct = float(verba_peri["percentual"] or 0.30)
            peri_budget = salario * pct
            origem = f"Verba #{verba_peri['id']}: {_fmt_moeda(salario)} x {_fmt_pct(pct)} = {_fmt_moeda(peri_budget)}"
            vig = f"{verba_peri['vigencia_inicio']}~{verba_peri['vigencia_fim'] or ''}"
        else:
            peri_budget = salario * 0.30
            origem = f"Padrão: {_fmt_moeda(salario)} x 30% = {_fmt_moeda(peri_budget)}"
            vig = ""
        linha("PERI", "Periculosidade", "adicional", peri_realizada, peri_budget, origem,
              id_param=verba_peri["id"] if verba_peri else None, vig=vig)
    else:
        peri_budget = 0.0

    base_rem = salario + peri_budget
    pct_peri = (peri_budget / salario) if salario else 0.0
    salario_hora = (salario / horas_mes) * (1 + pct_peri) if horas_mes else 0.0
    pode_he = (cargo_bd["pode_he"] if cargo_bd and cargo_bd.get("pode_he") is not None else (vinculo_bd["pode_he"] if vinculo_bd else True))
    pode_ben = (cargo_bd["pode_beneficios"] if cargo_bd and cargo_bd.get("pode_beneficios") is not None else (vinculo_bd["pode_beneficios"] if vinculo_bd else True))
    tem_fgts = False if estagiario else (cargo_bd["tem_fgts"] if cargo_bd and cargo_bd.get("tem_fgts") is not None else (vinculo_bd["tem_fgts"] if vinculo_bd else True))
    tem_inss = False if estagiario else (cargo_bd["tem_inss"] if cargo_bd and cargo_bd.get("tem_inss") is not None else (vinculo_bd["tem_inss_patronal"] if vinculo_bd else True))
    tem_13 = False if estagiario else (cargo_bd["tem_d13"] if cargo_bd and cargo_bd.get("tem_d13") is not None else (vinculo_bd["tem_decimo_terceiro"] if vinculo_bd else True))
    tem_ferias = cargo_bd["tem_ferias"] if cargo_bd and cargo_bd.get("tem_ferias") is not None else (vinculo_bd["tem_ferias"] if vinculo_bd else True)
    tem_terco = False if estagiario else (cargo_bd["tem_terca"] if cargo_bd and cargo_bd.get("tem_terca") is not None else (vinculo_bd["tem_um_terco"] if vinculo_bd else True))
    tem_aviso = False if estagiario else (cargo_bd["tem_aviso"] if cargo_bd and cargo_bd.get("tem_aviso") is not None else (vinculo_bd["tem_aviso_previo"] if vinculo_bd else True))
    tem_plr = False if estagiario else (cargo_bd["tem_plr"] if cargo_bd and cargo_bd.get("tem_plr") is not None else (vinculo_bd["tem_plr"] if vinculo_bd else True))
    base_encargos = peri_budget

    # ── ADICIONAL 25% ─────────────────────────────────────────
    pct_25 = float(cargo_bd["pct_adicional_25"] if cargo_bd else 0)
    adic25_bloqueado, _ = bloqueado("ADIC25")
    if pct_25 > 0 and not adic25_bloqueado:
        exc = _buscar_excecao(db, matricula, "ADIC25", empresa_codigo, competencia)
        if exc and exc.get("percentual") is not None:
            pct = float(exc["percentual"])
            fonte_adic25 = f"Exceção #{exc['id']}"
        else:
            pct, fonte_adic25 = regra_percentual("ADIC25", pct_25)
        val = base_rem * pct
        linha("ADIC25", "Adicional 25%", "adicional", None, val,
              f"{fonte_adic25}: {_fmt_moeda(base_rem)} x {_fmt_pct(pct)} = {_fmt_moeda(val)}")
        base_encargos += val

    # ── HE SOBRE ADICIONAL 25% ───────────────────────────────
    pct_he25 = float(cargo_bd["pct_he_sobre_25"] if cargo_bd else 0)
    bate_ponto = cargo_bd["bate_ponto"] if cargo_bd else True
    he25_bloqueado, _ = bloqueado("HE25")
    if pct_he25 > 0 and bate_ponto and pode_he and not estagiario and not he25_bloqueado:
        qtd = _buscar_quantidade(db, "he_sobre_25", competencia, cenario,
                                  empresa_codigo, matricula, codigo_cargo, grupo, cc)
        qtd = qtd or regra_quantidade("QTD_HE25", 10)
        pct_he25_regra, fonte_he25 = regra_percentual("HE25", pct_he25)
        val = salario_hora * qtd * pct_he25_regra
        if val:
            linha("HE25", "HE sobre Adicional 25%", "he", None, val,
                  f"{fonte_he25}: salário hora {_fmt_moeda(salario_hora)} x qtd {_fmt_num(qtd)} x {_fmt_pct(pct_he25_regra)} = {_fmt_moeda(val)}")
            base_encargos += val

    # ── HE 50% e 100% ────────────────────────────────────────
    if bate_ponto and pode_he and not estagiario:
        for cod, desc, fator, param in [
            ("HE50", "Hora Extra 50%", 1.5, "he_50"),
            ("HE100", "Hora Extra 100%", 2.0, "he_100"),
        ]:
            he_bloqueado, _ = bloqueado(cod)
            if he_bloqueado:
                continue
            qtd = _buscar_quantidade(db, param, competencia, cenario,
                                      empresa_codigo, matricula, codigo_cargo, grupo, cc)
            if not qtd and param == "he_50":
                qtd = regra_quantidade("QTD_HE50", 1)
            if not qtd and param == "he_100":
                qtd = regra_quantidade("QTD_HE100", 0)
            fator, fonte_he = regra_percentual(cod, fator)
            val = salario_hora * qtd * fator
            if val:
                linha(cod, desc, "he", None, val,
                      f"{fonte_he}: salário hora {_fmt_moeda(salario_hora)} x qtd {_fmt_num(qtd)} x {_fmt_num(fator, 2)} = {_fmt_moeda(val)}")
                base_encargos += val

    # ── ADICIONAL NOTURNO ─────────────────────────────────────
    noturno_bloqueado, _ = bloqueado("NOTURNO")
    if bate_ponto and pode_he and not estagiario and not noturno_bloqueado:
        verba_not = _buscar_verba_vigente(db, "NOTURNO", competencia)
        if buscar_regra("NOTURNO"):
            pct_not, fonte_not = regra_percentual("NOTURNO", 0.35)
        else:
            pct_not = float(verba_not["percentual"] if verba_not else 0.35)
            fonte_not = f"Verba #{verba_not['id']}" if verba_not else "Padrão"
        qtd = _buscar_quantidade(db, "noturno", competencia, cenario,
                                  empresa_codigo, matricula, codigo_cargo, grupo, cc)
        qtd = qtd or regra_quantidade("QTD_NOTURNO", 3)
        val = salario_hora * qtd * pct_not
        if val:
            linha("NOTURNO", "Adicional Noturno", "adicional", None, val,
                  f"{fonte_not}: salário hora {_fmt_moeda(salario_hora)} x qtd {_fmt_num(qtd)} x {_fmt_pct(pct_not)} = {_fmt_moeda(val)}")
            base_encargos += val

    # ── APOIADOR DE ETAPA / PRÊMIO ───────────────────────────
    regra_apoio = buscar_regra("APOIO_ETAPA")
    if not estagiario and regra_apoio:
        apoio_bloqueado, _ = bloqueado("APOIO_ETAPA")
        if not apoio_bloqueado:
            pct_apoio = float(regra_apoio.get("percentual") or 0.15)
            val = base_rem * pct_apoio
            linha("APOIO_ETAPA", "Apoiador Etapa", "adicional", None, val,
                  f"Regra #{regra_apoio['id']}: {_fmt_moeda(base_rem)} x {_fmt_pct(pct_apoio)} = {_fmt_moeda(val)}")
            base_encargos += val

    if not estagiario and _empresa_contem(empresa_nome, "PIRES"):
        premio_bloqueado, _ = bloqueado("PREMIO_PIRES")
        pct_premio, fonte_premio = regra_percentual("PREMIO_PIRES", 0.20)
        if not premio_bloqueado:
            val = base_rem * pct_premio
            linha("PREMIO_PIRES", "Prêmio", "adicional", None, val,
                  f"{fonte_premio}: {_fmt_moeda(base_rem)} x {_fmt_pct(pct_premio)} = {_fmt_moeda(val)}")
            base_encargos += val

    # ── EXCEÇÕES INDIVIDUAIS (verbas genéricas) ───────────────
    excecoes = db.execute(
        select(budget_excecoes)
        .where(budget_excecoes.c.matricula == matricula)
        .where(budget_excecoes.c.status == "Ativo")
        .where(budget_excecoes.c.codigo_verba.not_in(["PERI", "ADIC25"]))
    ).mappings().all()
    for exc in excecoes:
        if not _vigente(exc, competencia):
            continue
        val_exc = float(exc.get("valor") or 0)
        pct_exc = float(exc.get("percentual") or 0)
        qtd_exc = float(exc.get("quantidade") or 0)
        if pct_exc:
            val_exc = base_rem * pct_exc
            origem_exc = f"Exceção #{exc['id']}: {_fmt_moeda(base_rem)} x {_fmt_pct(pct_exc)} = {_fmt_moeda(val_exc)}"
        elif qtd_exc:
            val_exc = salario_hora * qtd_exc
            origem_exc = f"Exceção #{exc['id']}: salário hora {_fmt_moeda(salario_hora)} x qtd {_fmt_num(qtd_exc)} = {_fmt_moeda(val_exc)}"
        else:
            origem_exc = f"Exceção #{exc['id']}: valor fixo = {_fmt_moeda(val_exc)}"
        if val_exc:
            linha(exc["codigo_verba"], exc["descricao_verba"] or exc["codigo_verba"],
                  "adicional", None, val_exc, origem_exc)
            base_encargos += val_exc

    # ── BENEFÍCIOS ────────────────────────────────────────────
    beneficios_lancados = set()
    if pode_ben:
        beneficios_ativos = db.execute(
            select(budget_beneficios).where(budget_beneficios.c.status == "Ativo")
        ).mappings().all()
        for ben in beneficios_ativos:
            if not _vigente(ben, competencia):
                continue
            cod = ben["codigo"]
            if cod in beneficios_lancados:
                continue
            ben_bloqueado, _ = bloqueado(cod)
            if ben_bloqueado:
                beneficios_lancados.add(cod)
                continue
            # filtro elegibilidade
            if ben["empresa_codigo"] and ben["empresa_codigo"] != empresa_codigo:
                continue
            if ben["vinculo_codigo"] and ben["vinculo_codigo"] != vinculo:
                continue
            if ben["cargo_grupo"] and ben["cargo_grupo"] != grupo:
                continue
            beneficios_lancados.add(cod)
            val_fixo = float(ben["valor_fixo"] or 0)
            val_unit = float(ben["valor_unitario"] or 0)
            qtd = float(ben["quantidade"] or 0)
            pct_emp = float(ben["pct_empresa"] or 1)
            por_dep = ben["por_dependente"]

            if ben["codigo"] == "VR":
                qtd_dias = _buscar_quantidade(db, "dias_vr", competencia, cenario,
                                               empresa_codigo, matricula, codigo_cargo, grupo, cc)
                qtd = qtd_dias or qtd
            val = (val_fixo or (val_unit * qtd)) * pct_emp
            if por_dep:
                val = val * (1 + dependentes)
            if val:
                if val_fixo:
                    origem_ben = f"Benefício #{ben['id']}: valor fixo {_fmt_moeda(val_fixo)}"
                    if por_dep:
                        origem_ben += f" x (1 + dependentes {dependentes})"
                    if pct_emp != 1:
                        origem_ben += f" x {_fmt_pct(pct_emp)}"
                    origem_ben += f" = {_fmt_moeda(val)}"
                else:
                    origem_ben = (
                        f"Benefício #{ben['id']}: {_fmt_moeda(val_unit)} x qtd {_fmt_num(qtd)}"
                    )
                    if por_dep:
                        origem_ben += f" x (1 + dependentes {dependentes})"
                    if pct_emp != 1:
                        origem_ben += f" x {_fmt_pct(pct_emp)}"
                    origem_ben += f" = {_fmt_moeda(val)}"
                linha(cod, ben["descricao"], "beneficio", None, val, origem_ben,
                      vig=f"{ben['vigencia_inicio']}~{ben['vigencia_fim'] or ''}")

        vr_bloqueado, _ = bloqueado("VR")
        if "VR" not in beneficios_lancados and not vr_bloqueado:
            valor_dia_vr, fonte_vr = regra_valor("VR_DIA", 38)
            qtd_dias = _buscar_quantidade(db, "dias_vr", competencia, cenario,
                                           empresa_codigo, matricula, codigo_cargo, grupo, cc)
            qtd_dias = qtd_dias or regra_quantidade("QTD_DIAS_VR", 22)
            val = valor_dia_vr * qtd_dias
            linha("VR", "Vale Refeição", "beneficio", None, val,
                  f"{fonte_vr}: {_fmt_moeda(valor_dia_vr)} x {_fmt_num(qtd_dias)} dias = {_fmt_moeda(val)}")
            beneficios_lancados.add("VR")

        for cod, desc, fallback in [
            ("VA", "Vale Alimentação", 313),
            ("COMB", "Vale Combustível", 397.75),
            ("ACADEMIA", "Academia", 53),
        ]:
            cod_bloqueado, _ = bloqueado(cod)
            if cod not in beneficios_lancados and not cod_bloqueado:
                val, fonte = regra_valor(cod, fallback)
                if val:
                    linha(cod, desc, "beneficio", None, val, f"{fonte}: valor fixo = {_fmt_moeda(val)}")
                    beneficios_lancados.add(cod)

        saude_bloqueado, _ = bloqueado("SAUDE")
        if "SAUDE" not in beneficios_lancados and not saude_bloqueado:
            fallback_saude = 615.55
            if _normalizar_cargo(nivel1) == "DIRETOR":
                fallback_saude = 2423.38
            elif _normalizar_cargo(nivel1) == "GERENTE":
                fallback_saude = 1873.31
            elif _normalizar_cargo(nivel1) in {"SUPERVISOR", "COORDENADORES"}:
                fallback_saude = 748.86
            valor_saude, fonte = regra_valor("SAUDE", fallback_saude)
            val_saude = valor_saude * (1 + dependentes)
            linha("SAUDE", "Assistência Médica", "beneficio", None,
                  val_saude,
                  f"{fonte} {nivel1 or 'geral'}: {_fmt_moeda(valor_saude)} x (1 + dependentes {dependentes}) = {_fmt_moeda(val_saude)}")

        odonto_bloqueado, _ = bloqueado("ODONTO")
        if "ODONTO" not in beneficios_lancados and not odonto_bloqueado:
            valor_odonto, fonte = regra_valor("ODONTO", 11.24)
            val_odonto = valor_odonto * (1 + dependentes)
            linha("ODONTO", "Assistência Odontológica", "beneficio", None,
                  val_odonto,
                  f"{fonte}: {_fmt_moeda(valor_odonto)} x (1 + dependentes {dependentes}) = {_fmt_moeda(val_odonto)}")

        seguro_bloqueado, _ = bloqueado("SEGURO_VIDA")
        if "SEGURO_VIDA" not in beneficios_lancados and not seguro_bloqueado:
            fallback_seguro = 0.0
            if _empresa_contem(empresa_nome, "DENER"):
                fallback_seguro = 52.18 if _normalizar_cargo(nivel1) == "DIRETOR" else 13.04
            elif _empresa_contem(empresa_nome, "GT3"):
                fallback_seguro = 56.86 if _normalizar_cargo(nivel1) == "DIRETOR" else 20.39
            elif _empresa_contem(empresa_nome, "PIRES"):
                fallback_seguro = 0 if _normalizar_cargo(nivel1) == "DIRETOR" else 7.39
            seguro, fonte = regra_valor("SEGURO_VIDA", fallback_seguro)
            if seguro:
                linha("SEGURO_VIDA", "Seguro de Vida", "beneficio", None, seguro,
                      f"{fonte} {empresa_nome or empresa_codigo} / {nivel1 or 'geral'} = {_fmt_moeda(seguro)}")

    # ── PROVISÕES ─────────────────────────────────────────────
    provisoes_map = [
        ("PROV_FER", "Provisão Férias", tem_ferias, 1 / 12),
        ("PROV_1T", "Provisão 1/3 Férias", tem_terco, 1 / 36),
        ("PROV_13", "Provisão 13º Salário", tem_13, 1 / 12),
        ("PROV_AVI", "Provisão Aviso Prévio", tem_aviso, 1 / 12),
        ("PROV_PLR", "Provisão PLR", tem_plr, 1 / 12),
    ]
    for cod, desc, elegivel, fator in provisoes_map:
        if not elegivel:
            continue
        prov_bloqueada, _ = bloqueado(cod)
        if prov_bloqueada:
            continue
        enc = _buscar_encargo(db, cod, competencia, empresa_codigo, vinculo)
        if buscar_regra(cod):
            f, fonte_prov = regra_percentual(cod, fator)
        else:
            f = float(enc["percentual"] if enc else fator)
            fonte_prov = f"Encargo #{enc['id']}" if enc else "Padrão"
        val = base_rem * f
        linha(cod, desc, "provisao", None, val,
              f"{fonte_prov}: {_fmt_moeda(base_rem)} x {_fmt_pct(f)} = {_fmt_moeda(val)}")

    # ── ENCARGOS (FGTS, INSS Patronal) ───────────────────────
    encargos_map = [
        ("FGTS", "FGTS", tem_fgts, 0.08),
        ("INSS_PAT", "INSS Patronal", tem_inss, 0.268),
    ]
    for cod, desc, elegivel, padrao in encargos_map:
        if not elegivel:
            continue
        enc_bloqueado, _ = bloqueado(cod)
        if enc_bloqueado:
            continue
        enc = _buscar_encargo(db, cod, competencia, empresa_codigo, vinculo)
        if buscar_regra(cod):
            pct, fonte_enc = regra_percentual(cod, padrao)
        else:
            pct = float(enc["percentual"] if enc else padrao)
            fonte_enc = f"Encargo #{enc['id']}" if enc else "Padrão"
        val = base_encargos * pct
        if cod == "INSS_PAT" and _empresa_contem(empresa_nome, "PIRES"):
            val = 0
            origem_enc = f"PIRES: INSS patronal zerado sobre base {_fmt_moeda(base_encargos)}"
        else:
            origem_enc = (
                f"{fonte_enc}: "
                f"base encargos {_fmt_moeda(base_encargos)} x {_fmt_pct(pct)} = {_fmt_moeda(val)}"
            )
        linha(cod, desc, "encargo", None, val,
              origem_enc)

    return resultados


# ─────────────────────────────────────────────────────────────
# ROTAS — HUB
# ─────────────────────────────────────────────────────────────

@router.get("/folha/budget")
def budget_index(request: Request, db: Session = Depends(get_db)):
    from app.routers.folha_pagamento import folha_funcionarios as ff
    competencias_folha = db.execute(
        select(ff.c.competencia).distinct().order_by(ff.c.competencia)
    ).scalars().all()
    qtd_verbas = db.execute(
        select(text("count(*)")).select_from(budget_verbas)
    ).scalar() or 0
    qtd_cargos = db.execute(
        select(text("count(*)")).select_from(budget_cargos)
    ).scalar() or 0
    qtd_empresas = db.execute(
        select(text("count(*)")).select_from(budget_empresas)
    ).scalar() or 0
    qtd_regras = db.execute(
        select(text("count(*)")).select_from(budget_regras)
    ).scalar() or 0
    qtd_cargos_niveis = db.execute(
        select(text("count(*)")).select_from(budget_cargos_niveis)
    ).scalar() or 0
    qtd_excecoes = db.execute(
        select(text("count(*)")).select_from(budget_excecoes)
    ).scalar() or 0
    return templates.TemplateResponse("folha/budget_index.html", {
        "request": request,
        "competencias_folha": competencias_folha,
        "qtd_verbas": qtd_verbas,
        "qtd_cargos": qtd_cargos,
        "qtd_empresas": qtd_empresas,
        "qtd_regras": qtd_regras,
        "qtd_cargos_niveis": qtd_cargos_niveis,
        "qtd_excecoes": qtd_excecoes,
    })


# ─────────────────────────────────────────────────────────────
# ROTAS — CENTRAL DE REGRAS
# ─────────────────────────────────────────────────────────────

@router.get("/folha/budget/regras")
def budget_regras_list(request: Request, db: Session = Depends(get_db)):
    from app.routers.folha_pagamento import folha_arquivos, folha_funcionarios as ff

    categoria = request.query_params.get("categoria", "").strip()
    vigencia_filtro = request.query_params.get("vigencia", "").strip()
    q = select(budget_regras)
    if categoria:
        q = q.where(budget_regras.c.categoria == categoria)
    rows_raw = db.execute(
        q.order_by(budget_regras.c.categoria, budget_regras.c.codigo, budget_regras.c.prioridade)
    ).mappings().all()
    itens = []
    for row in rows_raw:
        item = dict(row)
        item["vigencia_status"] = _status_vigencia_regra(item)
        tem_fim_vigencia = bool(str(item.get("vigencia_fim") or "").strip())
        if vigencia_filtro == "ativa" and tem_fim_vigencia:
            continue
        if vigencia_filtro == "encerrada" and not tem_fim_vigencia:
            continue
        item["vigencia_label"] = _fmt_vigencia_regra(item)
        item["condicoes_resumo"] = _resumo_condicoes(item)
        item["excecoes_detalhes"] = _detalhes_excecoes_regra(item)
        item["modal_payload"] = _regra_modal_payload(item)
        item["tem_recorte"] = _regra_tem_recorte(item)
        itens.append(item)
    grupos: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in itens:
        grupos.setdefault((item.get("categoria") or "", item.get("codigo") or ""), []).append(item)

    rows = []
    for (_categoria, _codigo), filhos in grupos.items():
        filhos = sorted(filhos, key=lambda r: (int(r.get("prioridade") or 99), int(r.get("id") or 0)))
        principal = next((r for r in filhos if not r["tem_recorte"]), filhos[0])
        grupo = dict(principal)
        grupo["id"] = f"grp-{principal['codigo']}"
        grupo["children"] = filhos
        grupo["children_count"] = len(filhos)
        grupo["is_group"] = len(filhos) > 1
        grupo["modal_payload"] = _regra_modal_payload(principal)
        grupo["condicoes_resumo"] = f"{len(filhos)} variações" if len(filhos) > 1 else principal["condicoes_resumo"]
        grupo["excecoes_detalhes"] = []
        rows.append(grupo)
    rows.sort(key=lambda r: (r.get("categoria") or "", r.get("codigo") or "", int(r.get("prioridade") or 99)))
    categorias = db.execute(
        select(budget_regras.c.categoria).distinct().order_by(budget_regras.c.categoria)
    ).scalars().all()
    niveis_rows = db.execute(
        select(
            budget_cargos_niveis.c.nivel1,
            budget_cargos_niveis.c.nivel2,
            budget_cargos_niveis.c.nivel3,
        )
    ).all()
    niveis = sorted({
        str(valor).strip()
        for row in niveis_rows
        for valor in row
        if str(valor or "").strip()
    })
    cargos = db.execute(
        select(budget_cargos_niveis.c.cargo)
        .where(budget_cargos_niveis.c.status == "Ativo")
        .order_by(budget_cargos_niveis.c.cargo)
    ).scalars().all()
    empresas_folha = db.execute(
        select(folha_arquivos.c.empresa_nome)
        .where(folha_arquivos.c.empresa_nome.isnot(None))
        .where(folha_arquivos.c.empresa_nome != "")
        .distinct()
        .order_by(folha_arquivos.c.empresa_nome)
    ).scalars().all()
    empresas_budget = db.execute(
        select(budget_empresas.c.razao_social)
        .where(budget_empresas.c.razao_social.isnot(None))
        .where(budget_empresas.c.razao_social != "")
        .distinct()
        .order_by(budget_empresas.c.razao_social)
    ).scalars().all()
    nomes = db.execute(
        select(ff.c.nome)
        .where(ff.c.nome.isnot(None))
        .where(ff.c.nome != "")
        .distinct()
        .order_by(ff.c.nome)
        .limit(500)
    ).scalars().all()
    matriculas = db.execute(
        select(ff.c.matricula)
        .where(ff.c.matricula.isnot(None))
        .where(ff.c.matricula != "")
        .distinct()
        .order_by(ff.c.matricula)
        .limit(500)
    ).scalars().all()
    centros_custo = db.execute(
        select(ff.c.centro_custo)
        .where(ff.c.centro_custo.isnot(None))
        .where(ff.c.centro_custo != "")
        .distinct()
        .order_by(ff.c.centro_custo)
    ).scalars().all()
    condicao_opcoes = {
        "matricula": list(matriculas),
        "nome": list(nomes),
        "cargo": list(cargos),
        "nivel1": niveis,
        "empresa": sorted(set(list(empresas_folha) + list(empresas_budget))),
        "centro_custo": list(centros_custo),
    }
    comp_padrao = date.today().strftime("%Y-%m")
    return templates.TemplateResponse("folha/budget_regras.html", {
        "request": request,
        "rows": rows,
        "categorias": categorias,
        "categoria_sel": categoria,
        "vigencia_sel": vigencia_filtro,
        "condicao_opcoes": condicao_opcoes,
        "competencia_padrao": comp_padrao,
        "fmt_pct": _fmt_pct,
        "success": request.query_params.get("success"),
        "error": request.query_params.get("error"),
    })


@router.post("/folha/budget/regras")
async def budget_regras_salvar(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    count = int(form.get("rows_count", 1))
    modo = form.get("modo_aplicacao", "nova_vigencia")
    inicio = _inicio_competencia(form.get("competencia_aplicacao"))
    usuario = _usuario(request)
    salvos = 0

    for i in range(count):
        suffix = f"_{i}" if form.get(f"codigo_{i}") is not None else ""
        codigo = (form.get(f"codigo{suffix}") or "").strip()
        descricao = (form.get(f"descricao{suffix}") or "").strip()
        if not codigo or not descricao:
            continue
        id_val = (form.get(f"id{suffix}") or "").strip()
        condicoes_json = (form.get(f"condicoes_json{suffix}") or "").strip()
        condicao_campo = (form.get(f"condicao_campo{suffix}") or "").strip()
        condicao_operador = (form.get(f"condicao_operador{suffix}") or "").strip()
        condicao_valor = (form.get(f"condicao_valor{suffix}") or "").strip()
        if condicoes_json:
            try:
                condicoes_form = json.loads(condicoes_json)
                primeira = next((c for c in condicoes_form if c.get("campo") and c.get("valor")), None)
                if primeira:
                    condicao_campo = str(primeira.get("campo") or "").strip()
                    condicao_operador = str(primeira.get("operador") or "contem").strip()
                    condicao_valor = str(primeira.get("valor") or "").strip()
            except Exception:
                condicoes_json = ""
        dados = dict(
            codigo=codigo,
            descricao=descricao,
            categoria=form.get(f"categoria{suffix}") or "beneficio",
            tipo_calculo=form.get(f"tipo{suffix}") or "valor_fixo",
            valor=float(form.get(f"valor{suffix}") or 0),
            quantidade=float(form.get(f"quantidade{suffix}") or 0),
            percentual=_parse_pct_form(form.get(f"percentual{suffix}") or 0),
            aplicacao=form.get(f"aplicacao{suffix}") or "calcular",
            matriculas=(form.get(f"matriculas{suffix}") or "").strip() or None,
            condicao_campo=condicao_campo or None,
            condicao_operador=condicao_operador or None,
            condicao_valor=condicao_valor or None,
            condicoes_json=condicoes_json or None,
            empresa_contem=(form.get(f"empresa{suffix}") or "").strip() or None,
            nivel1=(form.get(f"nivel1{suffix}") or "").strip() or None,
            codigo_cargo=(form.get(f"cargo{suffix}") or "").strip() or None,
            vinculo_codigo=(form.get(f"vinculo{suffix}") or "").strip() or None,
            prioridade=int(form.get(f"prioridade{suffix}") or 99),
            status=form.get(f"status{suffix}", "Ativo"),
            vigencia_fim=None,
        )

        if id_val:
            atual = db.execute(
                select(budget_regras).where(budget_regras.c.id == int(id_val))
            ).mappings().first()
            campos_texto = [
                "codigo", "descricao", "categoria", "tipo_calculo", "empresa_contem",
                "nivel1", "codigo_cargo", "vinculo_codigo", "aplicacao", "matriculas",
                "condicao_campo", "condicao_operador", "condicao_valor", "condicoes_json", "status",
            ]
            campos_num = ["valor", "quantidade", "percentual"]
            igual = bool(atual)
            if atual:
                for campo in campos_texto:
                    if (atual.get(campo) or "") != (dados.get(campo) or ""):
                        igual = False
                        break
                if igual:
                    for campo in campos_num:
                        if round(float(atual.get(campo) or 0), 6) != round(float(dados.get(campo) or 0), 6):
                            igual = False
                            break
                if igual and int(atual.get("prioridade") or 99) != int(dados.get("prioridade") or 99):
                    igual = False
            if igual:
                continue

        if id_val and modo == "nova_vigencia":
            atual_inicio = str((atual or {}).get("vigencia_inicio") or "")
            if not atual_inicio or atual_inicio < inicio:
                db.execute(update(budget_regras).where(
                    budget_regras.c.id == int(id_val)
                ).values(vigencia_fim=_fim_mes_anterior(inicio)))
            _fechar_regras_abertas_anteriores(db, codigo, inicio, excluir_id=int(id_val))
            dados["vigencia_inicio"] = inicio
            dados["criado_por"] = usuario
            db.execute(insert(budget_regras).values(**dados))
        elif id_val:
            if modo == "retroagir":
                dados["vigencia_inicio"] = "2000-01-01"
            db.execute(update(budget_regras).where(
                budget_regras.c.id == int(id_val)
            ).values(**dados))
        else:
            dados["vigencia_inicio"] = "2000-01-01" if modo == "retroagir" else inicio
            dados["criado_por"] = usuario
            if modo == "nova_vigencia":
                _fechar_regras_abertas_anteriores(db, codigo, inicio)
            db.execute(insert(budget_regras).values(**dados))
        salvos += 1

    db.commit()
    msg = f"{salvos} regra(s) salva(s)."
    if modo == "nova_vigencia":
        msg += f" Nova vigência a partir de {inicio[:7]}."
    elif modo == "retroagir":
        msg += " Alteração retroativa aplicada."
    else:
        msg += " Registro atual sobrescrito."
    return redirect_with_message("/folha/budget/regras", success=msg)


@router.post("/folha/budget/regras/{id}/excluir")
def budget_regras_excluir(id: int, db: Session = Depends(get_db)):
    db.execute(delete(budget_regras).where(budget_regras.c.id == id))
    db.commit()
    return redirect_with_message("/folha/budget/regras", success="Regra excluída.")


# ─────────────────────────────────────────────────────────────
# ROTAS — NÍVEIS DE CARGO
# ─────────────────────────────────────────────────────────────

@router.get("/folha/budget/cargos-niveis")
def budget_cargos_niveis_list(request: Request, db: Session = Depends(get_db)):
    busca = request.query_params.get("q", "").strip()
    q = select(budget_cargos_niveis)
    if busca:
        termo = f"%{_normalizar_cargo(busca)}%"
        q = q.where(budget_cargos_niveis.c.cargo_normalizado.like(termo))
    rows = db.execute(
        q.order_by(budget_cargos_niveis.c.nivel1, budget_cargos_niveis.c.cargo)
    ).mappings().all()
    return templates.TemplateResponse("folha/budget_cargos_niveis.html", {
        "request": request,
        "rows": rows,
        "busca": busca,
        "pct_input": _fmt_pct_input,
        "success": request.query_params.get("success"),
        "error": request.query_params.get("error"),
    })


@router.post("/folha/budget/cargos-niveis")
async def budget_cargos_niveis_salvar(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    ids = form.getlist("row_id")
    usuario = _usuario(request)
    salvos = 0
    for row_id in ids:
        sid = str(row_id)
        cargo = (form.get(f"cargo_{sid}") or "").strip()
        if not cargo:
            continue
        dados = dict(
            cargo=cargo,
            cargo_normalizado=_normalizar_cargo(cargo),
            nivel1=(form.get(f"nivel1_{sid}") or "").strip(),
            nivel2=(form.get(f"nivel2_{sid}") or "").strip(),
            nivel3=(form.get(f"nivel3_{sid}") or "").strip(),
            tem_periculosidade=form.get(f"peric_{sid}") == "1",
            bate_ponto=form.get(f"bate_ponto_{sid}") == "1",
            pct_adicional_25=_parse_pct_form(form.get(f"pct25_{sid}") or 0),
            pct_he_sobre_25=_parse_pct_form(form.get(f"pcthe_{sid}") or 0),
            pode_he=form.get(f"pode_he_{sid}") == "1",
            status=form.get(f"status_{sid}") or "Ativo",
        )
        if sid.startswith("novo"):
            dados["criado_por"] = usuario
            db.execute(insert(budget_cargos_niveis).values(**dados))
        else:
            db.execute(update(budget_cargos_niveis).where(
                budget_cargos_niveis.c.id == int(sid)
            ).values(**dados))
        salvos += 1
    db.commit()
    return redirect_with_message("/folha/budget/cargos-niveis", success=f"{salvos} nível(is) de cargo salvo(s).")


# ─────────────────────────────────────────────────────────────
# ROTAS — EMPRESAS
# ─────────────────────────────────────────────────────────────

@router.get("/folha/budget/empresas")
def budget_empresas_list(request: Request, db: Session = Depends(get_db)):
    rows = db.execute(select(budget_empresas).order_by(budget_empresas.c.codigo)).mappings().all()
    return templates.TemplateResponse("folha/budget_empresas.html", {
        "request": request, "rows": rows,
        "success": request.query_params.get("success"),
        "error": request.query_params.get("error"),
    })

@router.post("/folha/budget/empresas")
def budget_empresas_salvar(
    request: Request, db: Session = Depends(get_db),
    id: str = Form(""), codigo: str = Form(...), razao_social: str = Form(...),
    cnpj: str = Form(""), status: str = Form("Ativo"),
    vigencia_inicio: str = Form(""), vigencia_fim: str = Form(""),
    fechar_anterior_id: str = Form(""),
):
    dados = dict(codigo=codigo.strip(), razao_social=razao_social.strip(),
                 cnpj=cnpj.strip(), status=status, vigencia_fim=vigencia_fim or None)
    if id.strip():
        dados["vigencia_inicio"] = vigencia_inicio or None
        db.execute(update(budget_empresas).where(budget_empresas.c.id == int(id)).values(**dados))
        msg = "Empresa atualizada."
    else:
        dados["vigencia_inicio"] = vigencia_inicio or "2000-01-01"
        dados["criado_por"] = _usuario(request)
        if fechar_anterior_id.strip():
            _fechar_vigencia(db, budget_empresas, int(fechar_anterior_id))
            msg = "Nova vigência de empresa criada."
        else:
            msg = "Empresa cadastrada."
        db.execute(insert(budget_empresas).values(**dados))
    db.commit()
    return redirect_with_message("/folha/budget/empresas", success=msg)

@router.post("/folha/budget/empresas/{id}/excluir")
def budget_empresas_excluir(id: int, db: Session = Depends(get_db)):
    db.execute(delete(budget_empresas).where(budget_empresas.c.id == id))
    db.commit()
    return redirect_with_message("/folha/budget/empresas", success="Empresa excluída.")


# ─────────────────────────────────────────────────────────────
# ROTAS — CARGOS
# ─────────────────────────────────────────────────────────────

@router.get("/folha/budget/cargos")
def budget_cargos_list(request: Request, db: Session = Depends(get_db)):
    filtro_competencia = request.query_params.get("competencia", "").strip()
    filtro_empresa = request.query_params.get("empresa", "").strip()
    filtro_cargo = request.query_params.get("cargo", "").strip()

    # Pessoas distintas da folha importada (por matrícula + competência mais recente)
    pessoas_folha = db.execute(
        text("""
            SELECT ff.matricula,
                   MAX(ff.nome) as nome,
                   MAX(ff.codigo_cargo) as codigo_cargo,
                   MAX(ff.cargo) as cargo,
                   MAX(ff.salario) as salario,
                   MAX(ff.horas_mes) as horas_mes,
                   MAX(COALESCE(ff.nd, 0)) as dependentes_folha,
                   ff.competencia,
                   MAX(fa.empresa_nome) as empresa,
                   MAX(ff.id_funcionario) as id_func
            FROM folha_funcionarios ff
            LEFT JOIN folha_arquivos fa ON fa.id_arquivo = ff.id_arquivo
            WHERE ff.matricula IS NOT NULL AND ff.matricula != ''
            GROUP BY ff.matricula, ff.competencia
            ORDER BY ff.competencia, MAX(ff.nome)
        """)
    ).mappings().all()

    # Checa se alguma rubrica de periculosidade foi paga por matricula+competencia
    perics = set()
    try:
        rows_peric = db.execute(text("""
            SELECT DISTINCT ff.matricula, ff.competencia
            FROM folha_rubricas fr
            JOIN folha_funcionarios ff ON ff.id_funcionario = fr.id_funcionario
            WHERE UPPER(fr.descricao) LIKE '%PERICULOSIDADE%'
        """)).fetchall()
        perics = {(r[0], r[1]) for r in rows_peric}
    except Exception:
        pass

    # Parâmetros já cadastrados no budget, indexados por matricula+competencia
    params_existentes: dict = {}
    for r in db.execute(
        select(budget_cargos).where(budget_cargos.c.status == "Ativo")
    ).mappings().all():
        chave = (r["matricula"] or "", r.get("competencia") or "")
        params_existentes[chave] = dict(r)

    # Mescla: base da folha + params cadastrados
    cargos = []
    for c in pessoas_folha:
        chave = (c["matricula"] or "", c["competencia"] or "")
        p = params_existentes.get(chave, {})
        recebeu_peric = chave in perics
        padrao_cargo = _buscar_nivel_cargo(db, c["cargo"]) or _parametros_padrao_cargo(c["cargo"])
        dependentes_padrao = p["dependentes"] if p and p.get("dependentes") is not None else (c["dependentes_folha"] or 0)
        periculosidade_padrao = bool(padrao_cargo.get("tem_periculosidade"))
        bate_ponto_padrao = p["bate_ponto"] if p and p.get("bate_ponto") is not None else padrao_cargo["bate_ponto"]
        pct_adicional_padrao = p["pct_adicional_25"] if p and p.get("pct_adicional_25") is not None else padrao_cargo["pct_adicional_25"]
        pct_he_padrao = p["pct_he_sobre_25"] if p and p.get("pct_he_sobre_25") is not None else padrao_cargo["pct_he_sobre_25"]
        pode_he_padrao = p["pode_he"] if p and p.get("pode_he") is not None else padrao_cargo["pode_he"]
        cargos.append({
            "competencia": c["competencia"] or "",
            "empresa": c["empresa"] or "",
            "matricula": c["matricula"],
            "nome": p.get("nome") or c["nome"] or "",
            "codigo_cargo": c["codigo_cargo"],
            "nome_folha": c["cargo"],
            "id": p.get("id", ""),
            "descricao": p.get("descricao") or c["cargo"] or "",
            "salario": p.get("salario") or c["salario"] or 0.0,
            "horas_mes": p.get("horas_mes") or c["horas_mes"] or 200.0,
            "dependentes": dependentes_padrao,
            "tem_periculosidade": periculosidade_padrao,
            "bate_ponto": bate_ponto_padrao,
            "pct_adicional_25": pct_adicional_padrao,
            "pct_he_sobre_25": pct_he_padrao,
            "tem_fgts": p.get("tem_fgts", True),
            "tem_inss": p.get("tem_inss", True),
            "tem_d13": p.get("tem_d13", True),
            "tem_ferias": p.get("tem_ferias", True),
            "tem_terca": p.get("tem_terca", True),
            "tem_aviso": p.get("tem_aviso", True),
            "tem_plr": p.get("tem_plr", False),
            "pode_he": pode_he_padrao,
            "pode_beneficios": p.get("pode_beneficios", True),
            "status": p.get("status", "Ativo"),
            "cadastrado": bool(p),
        })

    competencias = sorted({c["competencia"] for c in cargos if c["competencia"]})
    empresas = sorted({c["empresa"] for c in cargos if c["empresa"]})
    cargos_opcoes = sorted({c["descricao"] or c["nome_folha"] for c in cargos if c["descricao"] or c["nome_folha"]})

    if filtro_competencia:
        cargos = [c for c in cargos if c["competencia"] == filtro_competencia]
    if filtro_empresa:
        cargos = [c for c in cargos if c["empresa"] == filtro_empresa]
    if filtro_cargo:
        cargos = [c for c in cargos if (c["descricao"] or c["nome_folha"]) == filtro_cargo]

    return templates.TemplateResponse("folha/budget_cargos.html", {
        "request": request, "cargos": cargos,
        "competencias": competencias,
        "empresas": empresas,
        "cargos_opcoes": cargos_opcoes,
        "filtros": {
            "competencia": filtro_competencia,
            "empresa": filtro_empresa,
            "cargo": filtro_cargo,
        },
        "success": request.query_params.get("success"),
        "error": request.query_params.get("error"),
    })

@router.post("/folha/budget/cargos")
async def budget_cargos_salvar(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    usuario = _usuario(request)
    # chave: "mat_{matricula}__{competencia}"
    chaves = [k[4:] for k in form.keys() if k.startswith("mat_")]
    salvos = 0
    for chv in chaves:
        id_val = form.get(f"id_{chv}", "")
        mat = form.get(f"matricula_{chv}", chv)
        comp = form.get(f"comp_{chv}", "")
        cod = form.get(f"cod_{chv}", "")
        dados = dict(
            competencia=comp,
            matricula=mat,
            nome=form.get(f"nome_{chv}", "") or "",
            codigo_cargo=cod,
            descricao=form.get(f"desc_{chv}", "") or cod,
            salario=float(form.get(f"sal_{chv}") or 0),
            horas_mes=float(form.get(f"hrs_{chv}") or 200),
            dependentes=int(form.get(f"dep_{chv}") or 0),
            bate_ponto=form.get(f"ponto_{chv}") == "1",
            pct_adicional_25=_parse_pct_form(form.get(f"p25_{chv}") or 0),
            pct_he_sobre_25=_parse_pct_form(form.get(f"he25_{chv}") or 0),
            tem_fgts=form.get(f"fgts_{chv}") == "1",
            tem_inss=form.get(f"inss_{chv}") == "1",
            tem_d13=form.get(f"d13_{chv}") == "1",
            tem_ferias=form.get(f"fer_{chv}") == "1",
            tem_terca=form.get(f"t1_{chv}") == "1",
            tem_aviso=form.get(f"avi_{chv}") == "1",
            tem_plr=form.get(f"plr_{chv}") == "1",
            pode_he=form.get(f"he_{chv}") == "1",
            pode_beneficios=form.get(f"ben_{chv}") == "1",
            status=form.get(f"status_{chv}", "Ativo"),
            vigencia_fim=None,
        )
        if id_val.strip():
            db.execute(update(budget_cargos).where(
                budget_cargos.c.id == int(id_val)).values(**dados))
        else:
            dados["vigencia_inicio"] = "2000-01-01"
            dados["criado_por"] = usuario
            db.execute(insert(budget_cargos).values(**dados))
        salvos += 1
    db.commit()
    return redirect_with_message("/folha/budget/cargos", success=f"{salvos} pessoa(s) salva(s).")

@router.post("/folha/budget/cargos/{id}/excluir")
def budget_cargos_excluir(id: int, db: Session = Depends(get_db)):
    db.execute(delete(budget_cargos).where(budget_cargos.c.id == id))
    db.commit()
    return redirect_with_message("/folha/budget/cargos", success="Cargo excluído.")


# ─────────────────────────────────────────────────────────────
# ROTAS — VÍNCULOS
# ─────────────────────────────────────────────────────────────

@router.get("/folha/budget/vinculos")
def budget_vinculos_list(request: Request, db: Session = Depends(get_db)):
    rows = db.execute(select(budget_vinculos).order_by(budget_vinculos.c.codigo)).mappings().all()
    return templates.TemplateResponse("folha/budget_vinculos.html", {
        "request": request, "rows": rows,
        "success": request.query_params.get("success"),
        "error": request.query_params.get("error"),
    })

@router.post("/folha/budget/vinculos")
async def budget_vinculos_salvar(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    count = int(form.get("rows_count", 0))
    usuario = _usuario(request)
    salvos = 0
    for i in range(count):
        cod = (form.get(f"cod_{i}") or "").strip()
        if not cod:
            continue
        id_val = form.get(f"id_{i}", "")
        chk = lambda f: form.get(f"{f}_{i}") == "1"
        dados = dict(
            codigo=cod, descricao=form.get(f"desc_{i}", "") or None,
            tem_fgts=chk("fgts"), tem_inss_patronal=chk("inss"),
            tem_decimo_terceiro=chk("d13"), tem_ferias=chk("fer"),
            tem_um_terco=chk("t1"), tem_aviso_previo=chk("avi"),
            tem_plr=chk("plr"), pode_he=chk("he"), pode_beneficios=chk("ben"),
            status=form.get(f"status_{i}", "Ativo"), vigencia_fim=None,
        )
        if id_val.strip():
            db.execute(update(budget_vinculos).where(budget_vinculos.c.id == int(id_val)).values(**dados))
        else:
            dados["vigencia_inicio"] = "2000-01-01"
            dados["criado_por"] = usuario
            db.execute(insert(budget_vinculos).values(**dados))
        salvos += 1
    db.commit()
    return redirect_with_message("/folha/budget/vinculos", success=f"{salvos} vínculo(s) salvos.")

@router.post("/folha/budget/vinculos/{id}/excluir")
def budget_vinculos_excluir(id: int, db: Session = Depends(get_db)):
    db.execute(delete(budget_vinculos).where(budget_vinculos.c.id == id))
    db.commit()
    return redirect_with_message("/folha/budget/vinculos", success="Vínculo excluído.")


# ─────────────────────────────────────────────────────────────
# ROTAS — VERBAS
# ─────────────────────────────────────────────────────────────

@router.get("/folha/budget/verbas")
def budget_verbas_list(request: Request, db: Session = Depends(get_db)):
    rows = db.execute(select(budget_verbas).order_by(budget_verbas.c.codigo)).mappings().all()
    return templates.TemplateResponse("folha/budget_verbas.html", {
        "request": request, "rows": rows,
        "pct_input": _fmt_pct_input,
        "success": request.query_params.get("success"),
        "error": request.query_params.get("error"),
    })

@router.post("/folha/budget/verbas")
async def budget_verbas_salvar(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    count = int(form.get("rows_count", 0))
    usuario = _usuario(request)
    salvos = 0
    for i in range(count):
        cod = (form.get(f"cod_{i}") or "").strip()
        if not cod:
            continue
        id_val = form.get(f"id_{i}", "")
        chk = lambda f: form.get(f"{f}_{i}") == "1"
        dados = dict(
            codigo=cod, descricao=form.get(f"desc_{i}", cod),
            categoria=form.get(f"cat_{i}", "adicional"),
            tipo_calculo=form.get(f"tipo_{i}", "pct_salario"),
            base_calculo=form.get(f"base_{i}", "") or None,
            percentual=_parse_pct_form(form.get(f"pct_{i}") or 0),
            valor_fixo=float(form.get(f"vfix_{i}") or 0),
            quantidade_padrao=float(form.get(f"qtd_{i}") or 0),
            incide_inss=chk("inss"), incide_fgts=chk("fgts"),
            incide_ferias=chk("fer"), incide_decimo=chk("d13"),
            empresa_codigo=form.get(f"emp_{i}") or None,
            vinculo_codigo=form.get(f"vinc_{i}") or None,
            cargo_grupo=form.get(f"grp_{i}") or None,
            prioridade=int(form.get(f"pri_{i}") or 99),
            status=form.get(f"status_{i}", "Ativo"), vigencia_fim=None,
        )
        if id_val.strip():
            db.execute(update(budget_verbas).where(budget_verbas.c.id == int(id_val)).values(**dados))
        else:
            dados["vigencia_inicio"] = "2000-01-01"
            dados["criado_por"] = usuario
            db.execute(insert(budget_verbas).values(**dados))
        salvos += 1
    db.commit()
    return redirect_with_message("/folha/budget/verbas", success=f"{salvos} verba(s) salva(s).")

@router.post("/folha/budget/verbas/{id}/excluir")
def budget_verbas_excluir(id: int, db: Session = Depends(get_db)):
    db.execute(delete(budget_verbas).where(budget_verbas.c.id == id))
    db.commit()
    return redirect_with_message("/folha/budget/verbas", success="Verba excluída.")


# ─────────────────────────────────────────────────────────────
# ROTAS — BENEFÍCIOS
# ─────────────────────────────────────────────────────────────

@router.get("/folha/budget/beneficios")
def budget_beneficios_list(request: Request, db: Session = Depends(get_db)):
    rows = db.execute(select(budget_beneficios).order_by(budget_beneficios.c.codigo)).mappings().all()
    empresas = db.execute(select(budget_empresas.c.codigo, budget_empresas.c.razao_social)
                          .order_by(budget_empresas.c.codigo)).mappings().all()
    vinculos = db.execute(select(budget_vinculos.c.codigo)
                          .order_by(budget_vinculos.c.codigo)).scalars().all()
    return templates.TemplateResponse("folha/budget_beneficios.html", {
        "request": request, "rows": rows, "empresas": empresas, "vinculos": vinculos,
        "success": request.query_params.get("success"),
        "error": request.query_params.get("error"),
    })

@router.post("/folha/budget/beneficios")
async def budget_beneficios_salvar(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    count = int(form.get("rows_count", 0))
    usuario = _usuario(request)
    salvos = 0
    for i in range(count):
        cod = (form.get(f"cod_{i}") or "").strip()
        if not cod:
            continue
        id_val = form.get(f"id_{i}", "")
        dados = dict(
            codigo=cod, descricao=form.get(f"desc_{i}", cod),
            empresa_codigo=form.get(f"emp_{i}") or None,
            vinculo_codigo=form.get(f"vinc_{i}") or None,
            cargo_grupo=form.get(f"grp_{i}") or None,
            valor_fixo=float(form.get(f"vfix_{i}") or 0),
            valor_unitario=float(form.get(f"vunit_{i}") or 0),
            quantidade=float(form.get(f"qtd_{i}") or 0),
            por_dependente=form.get(f"dep_{i}") == "1",
            pct_empresa=float(form.get(f"pemp_{i}") or 1),
            status=form.get(f"status_{i}", "Ativo"), vigencia_fim=None,
        )
        if id_val.strip():
            db.execute(update(budget_beneficios).where(budget_beneficios.c.id == int(id_val)).values(**dados))
        else:
            dados["vigencia_inicio"] = "2000-01-01"
            dados["criado_por"] = usuario
            db.execute(insert(budget_beneficios).values(**dados))
        salvos += 1
    db.commit()
    return redirect_with_message("/folha/budget/beneficios", success=f"{salvos} benefício(s) salvos.")

@router.post("/folha/budget/beneficios/{id}/excluir")
def budget_beneficios_excluir(id: int, db: Session = Depends(get_db)):
    db.execute(delete(budget_beneficios).where(budget_beneficios.c.id == id))
    db.commit()
    return redirect_with_message("/folha/budget/beneficios", success="Benefício excluído.")


# ─────────────────────────────────────────────────────────────
# ROTAS — ENCARGOS
# ─────────────────────────────────────────────────────────────

@router.get("/folha/budget/encargos")
def budget_encargos_list(request: Request, db: Session = Depends(get_db)):
    rows = db.execute(select(budget_encargos).order_by(budget_encargos.c.codigo)).mappings().all()
    empresas = db.execute(select(budget_empresas.c.codigo, budget_empresas.c.razao_social)
                          .order_by(budget_empresas.c.codigo)).mappings().all()
    vinculos = db.execute(select(budget_vinculos.c.codigo)
                          .order_by(budget_vinculos.c.codigo)).scalars().all()
    return templates.TemplateResponse("folha/budget_encargos.html", {
        "request": request, "rows": rows, "empresas": empresas, "vinculos": vinculos,
        "pct_input": _fmt_pct_input,
        "success": request.query_params.get("success"),
        "error": request.query_params.get("error"),
    })

@router.post("/folha/budget/encargos")
async def budget_encargos_salvar(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    count = int(form.get("rows_count", 0))
    usuario = _usuario(request)
    salvos = 0
    for i in range(count):
        cod = (form.get(f"cod_{i}") or "").strip()
        if not cod:
            continue
        id_val = form.get(f"id_{i}", "")
        dados = dict(
            codigo=cod, descricao=form.get(f"desc_{i}", cod),
            empresa_codigo=form.get(f"emp_{i}") or None,
            vinculo_codigo=form.get(f"vinc_{i}") or None,
            percentual=_parse_pct_form(form.get(f"pct_{i}") or 0),
            divisor=float(form.get(f"div_{i}") or 1),
            verbas_base=form.get(f"vbase_{i}") or None,
            prioridade=int(form.get(f"pri_{i}") or 99),
            status=form.get(f"status_{i}", "Ativo"), vigencia_fim=None,
        )
        if id_val.strip():
            db.execute(update(budget_encargos).where(budget_encargos.c.id == int(id_val)).values(**dados))
        else:
            dados["vigencia_inicio"] = "2000-01-01"
            dados["criado_por"] = usuario
            db.execute(insert(budget_encargos).values(**dados))
        salvos += 1
    db.commit()
    return redirect_with_message("/folha/budget/encargos", success=f"{salvos} encargo(s) salvos.")

@router.post("/folha/budget/encargos/{id}/excluir")
def budget_encargos_excluir(id: int, db: Session = Depends(get_db)):
    db.execute(delete(budget_encargos).where(budget_encargos.c.id == id))
    db.commit()
    return redirect_with_message("/folha/budget/encargos", success="Encargo excluído.")


# ─────────────────────────────────────────────────────────────
# ROTAS — EXCEÇÕES INDIVIDUAIS
# ─────────────────────────────────────────────────────────────

@router.get("/folha/budget/excecoes")
def budget_excecoes_list(request: Request, db: Session = Depends(get_db)):
    rows = db.execute(select(budget_excecoes).order_by(
        budget_excecoes.c.empresa_codigo, budget_excecoes.c.matricula
    )).mappings().all()
    empresas = db.execute(select(budget_empresas.c.codigo, budget_empresas.c.razao_social)
                          .order_by(budget_empresas.c.codigo)).mappings().all()
    verbas = db.execute(select(budget_verbas.c.codigo, budget_verbas.c.descricao)
                        .order_by(budget_verbas.c.codigo)).mappings().all()
    return templates.TemplateResponse("folha/budget_excecoes.html", {
        "request": request, "rows": rows, "empresas": empresas, "verbas": verbas,
        "fmt_pct": _fmt_pct,
        "pct_input": _fmt_pct_input,
        "success": request.query_params.get("success"),
        "error": request.query_params.get("error"),
    })

@router.post("/folha/budget/excecoes")
def budget_excecoes_salvar(
    request: Request, db: Session = Depends(get_db),
    id: str = Form(""), empresa_codigo: str = Form(""), matricula: str = Form(...),
    codigo_verba: str = Form(...), descricao_verba: str = Form(""),
    percentual: str = Form(""), valor: str = Form(""), quantidade: str = Form(""),
    justificativa: str = Form(""), prioridade: str = Form("1"),
    status: str = Form("Ativo"), vigencia_inicio: str = Form(""), vigencia_fim: str = Form(""),
    fechar_anterior_id: str = Form(""),
):
    dados = dict(
        empresa_codigo=empresa_codigo or None, matricula=matricula.strip(),
        codigo_verba=codigo_verba.strip(), descricao_verba=descricao_verba.strip(),
        percentual=_parse_pct_form(percentual) if percentual.strip() else None,
        valor=float(valor) if valor.strip() else None,
        quantidade=float(quantidade) if quantidade.strip() else None,
        justificativa=justificativa.strip() or None, prioridade=int(prioridade or 1),
        status=status, vigencia_fim=vigencia_fim or None,
    )
    if id.strip():
        dados["vigencia_inicio"] = vigencia_inicio or None
        db.execute(update(budget_excecoes).where(budget_excecoes.c.id == int(id)).values(**dados))
        msg = "Exceção atualizada."
    else:
        dados["vigencia_inicio"] = vigencia_inicio or "2000-01-01"
        dados["criado_por"] = _usuario(request)
        if fechar_anterior_id.strip():
            _fechar_vigencia(db, budget_excecoes, int(fechar_anterior_id))
            msg = "Nova vigência de exceção criada."
        else:
            msg = "Exceção cadastrada."
        db.execute(insert(budget_excecoes).values(**dados))
    db.commit()
    return redirect_with_message("/folha/budget/excecoes", success=msg)

@router.post("/folha/budget/excecoes/{id}/excluir")
def budget_excecoes_excluir(id: int, db: Session = Depends(get_db)):
    db.execute(delete(budget_excecoes).where(budget_excecoes.c.id == id))
    db.commit()
    return redirect_with_message("/folha/budget/excecoes", success="Exceção excluída.")


# ─────────────────────────────────────────────────────────────
# ROTAS — QUANTIDADES PROJETADAS
# ─────────────────────────────────────────────────────────────

PARAMETROS_QTD = ["he_50", "he_100", "noturno", "he_sobre_25", "dias_vr"]

@router.get("/folha/budget/quantidades")
def budget_quantidades_list(request: Request, db: Session = Depends(get_db)):
    from app.routers.folha_pagamento import folha_arquivos, folha_funcionarios as ff

    # Competências disponíveis na folha importada
    competencias_folha = db.execute(
        select(ff.c.competencia).distinct().order_by(ff.c.competencia)
    ).scalars().all()

    comp = request.query_params.get("comp", "")
    filtro_empresa = request.query_params.get("empresa", "").strip()
    filtro_cargo = request.query_params.get("cargo", "").strip()
    cargos_folha = []
    q_empresas = (
        select(folha_arquivos.c.empresa_nome)
        .join(ff, ff.c.id_arquivo == folha_arquivos.c.id_arquivo)
        .where(folha_arquivos.c.empresa_nome.isnot(None))
        .where(folha_arquivos.c.empresa_nome != "")
    )
    if comp:
        q_empresas = q_empresas.where(ff.c.competencia == comp)
    empresas = db.execute(q_empresas.distinct().order_by(folha_arquivos.c.empresa_nome)).scalars().all()

    q_opcoes = (
        select(ff.c.cargo)
        .join(folha_arquivos, ff.c.id_arquivo == folha_arquivos.c.id_arquivo)
        .where(ff.c.cargo.isnot(None))
        .where(ff.c.cargo != "")
    )
    if comp:
        q_opcoes = q_opcoes.where(ff.c.competencia == comp)
    if filtro_empresa:
        q_opcoes = q_opcoes.where(folha_arquivos.c.empresa_nome == filtro_empresa)
    cargos_opcoes = db.execute(q_opcoes.distinct().order_by(ff.c.cargo)).scalars().all()

    qtd_existentes: dict = {}  # (codigo_cargo, parametro) -> {id, quantidade}
    qtd_padrao: dict = {}  # (codigo_cargo, parametro) -> quantidade padrão

    if comp:
        # Cargos distintos da folha para a competência selecionada
        q_cargos = (
            select(ff.c.codigo_cargo, ff.c.cargo)
            .join(folha_arquivos, ff.c.id_arquivo == folha_arquivos.c.id_arquivo)
            .where(ff.c.competencia == comp)
            .where(ff.c.codigo_cargo.isnot(None))
            .where(ff.c.codigo_cargo != "")
        )
        if filtro_empresa:
            q_cargos = q_cargos.where(folha_arquivos.c.empresa_nome == filtro_empresa)
        if filtro_cargo:
            q_cargos = q_cargos.where(ff.c.cargo == filtro_cargo)
        cargos_folha = db.execute(q_cargos.distinct().order_by(ff.c.cargo)).mappings().all()

        # Headcount por cargo
        sql_hc = """
            SELECT ff.codigo_cargo, COUNT(DISTINCT ff.matricula) as hc
            FROM folha_funcionarios ff
            JOIN folha_arquivos fa ON fa.id_arquivo = ff.id_arquivo
            WHERE ff.competencia=:comp
              AND ff.codigo_cargo IS NOT NULL
              AND ff.codigo_cargo!=''
        """
        params_hc = {"comp": comp}
        if filtro_empresa:
            sql_hc += " AND fa.empresa_nome=:empresa"
            params_hc["empresa"] = filtro_empresa
        if filtro_cargo:
            sql_hc += " AND ff.cargo=:cargo"
            params_hc["cargo"] = filtro_cargo
        sql_hc += " GROUP BY ff.codigo_cargo"
        rows_hc = db.execute(text(sql_hc), params_hc).mappings().all()
        headcount = {r["codigo_cargo"]: r["hc"] for r in rows_hc}

        # Quantidades já salvas
        rows_qtd = db.execute(
            select(budget_quantidades)
            .where(budget_quantidades.c.competencia == comp)
            .where(budget_quantidades.c.cenario == "Direcionamento")
        ).mappings().all()
        for r in rows_qtd:
            if r["codigo_cargo"]:
                qtd_existentes[(r["codigo_cargo"], r["parametro"])] = {
                    "id": r["id"], "quantidade": r["quantidade"] or 0
                }

        rows_cargos_param = db.execute(
            select(budget_cargos)
            .where(budget_cargos.c.competencia == comp)
            .where(budget_cargos.c.status == "Ativo")
        ).mappings().all()
        cargos_param: dict[str, dict[str, Any]] = {}
        for row in rows_cargos_param:
            codigo = row["codigo_cargo"]
            if codigo and codigo not in cargos_param:
                cargos_param[codigo] = dict(row)

        cargos_folha = [dict(c, hc=headcount.get(c["codigo_cargo"], 0)) for c in cargos_folha]
        for c in cargos_folha:
            defaults = _quantidades_padrao(cargos_param.get(c["codigo_cargo"]), c.get("cargo") or "")
            for parametro, valor in defaults.items():
                qtd_padrao[(c["codigo_cargo"], parametro)] = valor

    return templates.TemplateResponse("folha/budget_quantidades.html", {
        "request": request,
        "competencias_folha": competencias_folha,
        "comp": comp,
        "empresas": empresas,
        "cargos_opcoes": cargos_opcoes,
        "filtros": {
            "empresa": filtro_empresa,
            "cargo": filtro_cargo,
        },
        "cargos_folha": cargos_folha,
        "qtd_existentes": qtd_existentes,
        "qtd_padrao": qtd_padrao,
        "parametros": PARAMETROS_QTD,
        "success": request.query_params.get("success"),
        "error": request.query_params.get("error"),
    })

@router.post("/folha/budget/quantidades")
async def budget_quantidades_salvar(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    comp = form.get("competencia", "")
    usuario = _usuario(request)
    salvos = 0

    for par in PARAMETROS_QTD:
        # Cada cargo envia campos: qtd_{par}_{codigo_cargo} e id_{par}_{codigo_cargo}
        for key in form.keys():
            if not key.startswith(f"qtd_{par}_"):
                continue
            codigo_cargo = key[len(f"qtd_{par}_"):]
            qtd_val = float(form.get(key) or 0)
            id_val = form.get(f"id_{par}_{codigo_cargo}", "")
            dados = dict(
                cenario="Direcionamento", competencia=comp, parametro=par,
                quantidade=qtd_val, codigo_cargo=codigo_cargo or None,
                status="Ativo",
            )
            if id_val.strip():
                db.execute(update(budget_quantidades).where(
                    budget_quantidades.c.id == int(id_val)).values(**dados))
            else:
                dados["criado_por"] = usuario
                db.execute(insert(budget_quantidades).values(**dados))
            salvos += 1

    db.commit()
    return redirect_with_message(
        f"/folha/budget/quantidades?comp={comp}",
        success=f"{salvos} quantidade(s) salva(s) para {comp}."
    )

@router.post("/folha/budget/quantidades/{id}/excluir")
def budget_quantidades_excluir(id: int, db: Session = Depends(get_db)):
    db.execute(delete(budget_quantidades).where(budget_quantidades.c.id == id))
    db.commit()
    return redirect_with_message("/folha/budget/quantidades", success="Quantidade excluída.")


# ─────────────────────────────────────────────────────────────
# ROTA — PROCESSAMENTO DO BUDGET
# ─────────────────────────────────────────────────────────────

@router.post("/folha/budget/processar")
def budget_processar(
    request: Request, db: Session = Depends(get_db),
    competencia: str = Form(...),
    id_arquivo: str = Form(""),
):
    from app.routers.folha_pagamento import folha_arquivos, folha_funcionarios, folha_rubricas
    cenario = "Direcionamento"

    # Apaga resultados anteriores da mesma competência para reprocessar
    db.execute(
        delete(budget_resultado)
        .where(budget_resultado.c.competencia == competencia)
    )

    # Busca funcionários da folha
    q = (
        select(folha_funcionarios, folha_arquivos.c.empresa_nome,
               folha_arquivos.c.empresa_codigo, folha_arquivos.c.cnpj)
        .join(folha_arquivos, folha_funcionarios.c.id_arquivo == folha_arquivos.c.id_arquivo)
        .where(folha_funcionarios.c.competencia == competencia)
    )
    if id_arquivo.strip():
        q = q.where(folha_funcionarios.c.id_arquivo == int(id_arquivo))

    funcionarios = db.execute(q).mappings().all()
    if not funcionarios:
        return redirect_with_message(
            "/folha/budget/resultado",
            error=f"Nenhum funcionário encontrado para competência {competencia}."
        )

    usuario = _usuario(request)
    total = 0
    for fun in funcionarios:
        rubricas = db.execute(
            select(folha_rubricas)
            .where(folha_rubricas.c.id_funcionario == fun["id_funcionario"])
        ).mappings().all()
        linhas = _processar_empregado(db, dict(fun), list(rubricas), competencia, cenario, usuario)
        if linhas:
            db.execute(insert(budget_resultado), linhas)
            total += len(linhas)

    db.commit()
    return redirect_with_message(
        "/folha/budget/resultado",
        success=f"Budget processado: {len(funcionarios)} empregado(s), {total} linha(s) — {cenario} / {competencia}."
    )


# ─────────────────────────────────────────────────────────────
# ROTA — RESULTADO
# ─────────────────────────────────────────────────────────────

@router.get("/folha/budget/resultado")
def budget_resultado_view(
    request: Request, db: Session = Depends(get_db),
    competencia: str = "", empresa: str = "", matricula: str = "",
):
    from app.routers.folha_pagamento import folha_funcionarios as ff

    competencias = db.execute(
        select(ff.c.competencia).distinct().order_by(ff.c.competencia)
    ).scalars().all()

    linhas = []
    totais: dict[str, float] = {}
    if competencia:
        q = select(budget_resultado).where(budget_resultado.c.competencia == competencia)
        if empresa:
            q = q.where(budget_resultado.c.empresa_codigo == empresa)
        if matricula:
            q = q.where(budget_resultado.c.matricula == matricula)
        q = q.order_by(budget_resultado.c.nome_empregado, budget_resultado.c.categoria_verba)
        linhas = db.execute(q).mappings().all()
        for l in linhas:
            cat = l["categoria_verba"] or "outros"
            totais[cat] = totais.get(cat, 0) + (l["valor_budget"] or 0)

    return templates.TemplateResponse("folha/budget_resultado.html", {
        "request": request, "linhas": linhas, "totais": totais,
        "competencias": competencias,
        "sel_competencia": competencia,
        "sel_empresa": empresa, "sel_matricula": matricula,
        "success": request.query_params.get("success"),
        "error": request.query_params.get("error"),
    })
