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
    Column("codigo_cargo", String(40), nullable=False),
    Column("descricao", String(200)),
    Column("grupo", String(80)),
    Column("area", String(80)),
    Column("nivel", String(80)),
    Column("bate_ponto", Boolean, default=True),
    Column("pct_adicional_25", Float, default=0.0),
    Column("pct_he_sobre_25", Float, default=0.0),
    Column("status", String(20), default="Ativo"),
    Column("vigencia_inicio", String(10)),
    Column("vigencia_fim", String(10)),
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

try:
    from app.database import SessionLocal
    _db = SessionLocal()
    _seed_cenarios(_db)
    _db.close()
except Exception:
    pass


# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

def _usuario(request: Request) -> str:
    u = getattr(request.state, "current_user", None) or {}
    return u.get("nome") or u.get("email") or "sistema"


def _vigente(row, competencia: str) -> bool:
    """Verifica se um registro está vigente para a competência (YYYY-MM)."""
    inicio = str(row.get("vigencia_inicio") or "")
    fim = str(row.get("vigencia_fim") or "")
    if inicio and competencia < inicio[:7]:
        return False
    if fim and competencia > fim[:7]:
        return False
    return True


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

    # Salário-hora
    salario_hora = salario / horas_mes if horas_mes else 0

    # Periculosidade: busca primeiro exceção, depois verba parametrizada
    peri_realizada = next(
        (float(r.get("valor") or 0) for r in rubricas
         if "PERICULOSIDADE" in str(r.get("descricao") or "").upper()),
        0.0
    )
    tem_peri = peri_realizada > 0

    # Cargo e vínculo do cadastro
    cargo_bd = _buscar_cargo(db, codigo_cargo, competencia)
    grupo = (cargo_bd["grupo"] if cargo_bd else "") or ""
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

    # ── SALÁRIO ──────────────────────────────────────────────
    linha("SAL", "Salário", "remuneracao", salario, salario, "realizado")

    # ── PERICULOSIDADE ────────────────────────────────────────
    if tem_peri:
        exc = _buscar_excecao(db, matricula, "PERI", empresa_codigo, competencia)
        verba_peri = _buscar_verba_vigente(db, "PERI", competencia)
        if exc and exc.get("percentual") is not None:
            pct = float(exc["percentual"])
            peri_budget = salario * pct
            origem = f"excecao#{exc['id']}"
        elif verba_peri:
            pct = float(verba_peri["percentual"] or 0.30)
            peri_budget = salario * pct
            origem = f"verba#{verba_peri['id']}"
            vig = f"{verba_peri['vigencia_inicio']}~{verba_peri['vigencia_fim'] or ''}"
        else:
            peri_budget = salario * 0.30
            origem = "padrao_30pct"
            vig = ""
        linha("PERI", "Periculosidade", "adicional", peri_realizada, peri_budget, origem,
              vig=verba_peri["id"] if verba_peri else None)
    else:
        peri_budget = 0.0

    base_rem = salario + peri_budget
    pode_he = vinculo_bd["pode_he"] if vinculo_bd else True
    pode_ben = vinculo_bd["pode_beneficios"] if vinculo_bd else True
    tem_fgts = vinculo_bd["tem_fgts"] if vinculo_bd else True
    tem_inss = vinculo_bd["tem_inss_patronal"] if vinculo_bd else True
    tem_13 = vinculo_bd["tem_decimo_terceiro"] if vinculo_bd else True
    tem_ferias = vinculo_bd["tem_ferias"] if vinculo_bd else True
    tem_terco = vinculo_bd["tem_um_terco"] if vinculo_bd else True
    tem_aviso = vinculo_bd["tem_aviso_previo"] if vinculo_bd else True
    tem_plr = vinculo_bd["tem_plr"] if vinculo_bd else True

    # ── ADICIONAL 25% ─────────────────────────────────────────
    pct_25 = float(cargo_bd["pct_adicional_25"] if cargo_bd else 0)
    if pct_25 > 0:
        exc = _buscar_excecao(db, matricula, "ADIC25", empresa_codigo, competencia)
        pct = float(exc["percentual"]) if exc and exc.get("percentual") is not None else pct_25
        val = base_rem * pct
        linha("ADIC25", "Adicional 25%", "adicional", None, val,
              f"excecao#{exc['id']}" if exc else f"cargo#{cargo_bd['id']}")

    # ── HE SOBRE ADICIONAL 25% ───────────────────────────────
    pct_he25 = float(cargo_bd["pct_he_sobre_25"] if cargo_bd else 0)
    bate_ponto = cargo_bd["bate_ponto"] if cargo_bd else True
    if pct_he25 > 0 and bate_ponto and pode_he:
        qtd = _buscar_quantidade(db, "he_sobre_25", competencia, cenario,
                                  empresa_codigo, matricula, codigo_cargo, grupo, cc)
        sh = salario_hora * (1 + peri_budget / salario if salario else 0)
        val = sh * qtd * pct_he25
        if val:
            linha("HE25", "HE sobre Adicional 25%", "he", None, val, f"qtd_projetada/{cenario}")

    # ── HE 50% e 100% ────────────────────────────────────────
    if bate_ponto and pode_he:
        for cod, desc, fator, param in [
            ("HE50", "Hora Extra 50%", 1.5, "he_50"),
            ("HE100", "Hora Extra 100%", 2.0, "he_100"),
        ]:
            qtd = _buscar_quantidade(db, param, competencia, cenario,
                                      empresa_codigo, matricula, codigo_cargo, grupo, cc)
            val = salario_hora * qtd * fator
            if val:
                linha(cod, desc, "he", None, val, f"qtd_projetada/{cenario}")

    # ── ADICIONAL NOTURNO ─────────────────────────────────────
    if bate_ponto and pode_he:
        verba_not = _buscar_verba_vigente(db, "NOTURNO", competencia)
        pct_not = float(verba_not["percentual"] if verba_not else 0.35)
        qtd = _buscar_quantidade(db, "noturno", competencia, cenario,
                                  empresa_codigo, matricula, codigo_cargo, grupo, cc)
        val = salario_hora * qtd * pct_not
        if val:
            linha("NOTURNO", "Adicional Noturno", "adicional", None, val,
                  f"verba#{verba_not['id']}" if verba_not else "padrao_35pct")

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
        elif qtd_exc:
            val_exc = salario_hora * qtd_exc
        if val_exc:
            linha(exc["codigo_verba"], exc["descricao_verba"] or exc["codigo_verba"],
                  "adicional", None, val_exc, f"excecao#{exc['id']}")

    # ── BENEFÍCIOS ────────────────────────────────────────────
    if pode_ben:
        beneficios_ativos = db.execute(
            select(budget_beneficios).where(budget_beneficios.c.status == "Ativo")
        ).mappings().all()
        codigos_vistos = set()
        for ben in beneficios_ativos:
            if not _vigente(ben, competencia):
                continue
            cod = ben["codigo"]
            if cod in codigos_vistos:
                continue
            # filtro elegibilidade
            if ben["empresa_codigo"] and ben["empresa_codigo"] != empresa_codigo:
                continue
            if ben["vinculo_codigo"] and ben["vinculo_codigo"] != vinculo:
                continue
            if ben["cargo_grupo"] and ben["cargo_grupo"] != grupo:
                continue
            codigos_vistos.add(cod)
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
                linha(cod, ben["descricao"], "beneficio", None, val, f"beneficio#{ben['id']}",
                      vig=f"{ben['vigencia_inicio']}~{ben['vigencia_fim'] or ''}")

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
        enc = _buscar_encargo(db, cod, competencia, empresa_codigo, vinculo)
        f = float(enc["percentual"] if enc else fator)
        val = base_rem * f
        linha(cod, desc, "provisao", None, val,
              f"encargo#{enc['id']}" if enc else "padrao")

    # ── ENCARGOS (FGTS, INSS Patronal) ───────────────────────
    encargos_map = [
        ("FGTS", "FGTS", tem_fgts, 0.08),
        ("INSS_PAT", "INSS Patronal", tem_inss, 0.268),
    ]
    for cod, desc, elegivel, padrao in encargos_map:
        if not elegivel:
            continue
        enc = _buscar_encargo(db, cod, competencia, empresa_codigo, vinculo)
        pct = float(enc["percentual"] if enc else padrao)
        val = base_rem * pct
        linha(cod, desc, "encargo", None, val,
              f"encargo#{enc['id']}" if enc else f"padrao_{int(padrao*100)}pct")

    return resultados


# ─────────────────────────────────────────────────────────────
# ROTAS — HUB
# ─────────────────────────────────────────────────────────────

@router.get("/folha/budget")
def budget_index(request: Request, db: Session = Depends(get_db)):
    cenarios = db.execute(
        select(budget_cenarios).where(budget_cenarios.c.status == "Ativo")
        .order_by(budget_cenarios.c.ordem)
    ).mappings().all()
    qtd_verbas = db.execute(
        select(text("count(*)")).select_from(budget_verbas)
    ).scalar() or 0
    qtd_cargos = db.execute(
        select(text("count(*)")).select_from(budget_cargos)
    ).scalar() or 0
    qtd_empresas = db.execute(
        select(text("count(*)")).select_from(budget_empresas)
    ).scalar() or 0
    qtd_excecoes = db.execute(
        select(text("count(*)")).select_from(budget_excecoes)
    ).scalar() or 0
    return templates.TemplateResponse("folha/budget_index.html", {
        "request": request,
        "cenarios": cenarios,
        "qtd_verbas": qtd_verbas,
        "qtd_cargos": qtd_cargos,
        "qtd_empresas": qtd_empresas,
        "qtd_excecoes": qtd_excecoes,
    })


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
):
    dados = dict(codigo=codigo.strip(), razao_social=razao_social.strip(),
                 cnpj=cnpj.strip(), status=status,
                 vigencia_inicio=vigencia_inicio or None,
                 vigencia_fim=vigencia_fim or None)
    if id.strip():
        db.execute(update(budget_empresas).where(budget_empresas.c.id == int(id)).values(**dados))
        msg = "Empresa atualizada."
    else:
        dados["criado_por"] = _usuario(request)
        db.execute(insert(budget_empresas).values(**dados))
        msg = "Empresa cadastrada."
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
    rows = db.execute(select(budget_cargos).order_by(budget_cargos.c.codigo_cargo)).mappings().all()
    return templates.TemplateResponse("folha/budget_cargos.html", {
        "request": request, "rows": rows,
        "success": request.query_params.get("success"),
        "error": request.query_params.get("error"),
    })

@router.post("/folha/budget/cargos")
def budget_cargos_salvar(
    request: Request, db: Session = Depends(get_db),
    id: str = Form(""), codigo_cargo: str = Form(...),
    descricao: str = Form(""), grupo: str = Form(""), area: str = Form(""),
    nivel: str = Form(""), bate_ponto: str = Form("1"),
    pct_adicional_25: str = Form("0"), pct_he_sobre_25: str = Form("0"),
    status: str = Form("Ativo"), vigencia_inicio: str = Form(""), vigencia_fim: str = Form(""),
):
    dados = dict(
        codigo_cargo=codigo_cargo.strip(), descricao=descricao.strip(),
        grupo=grupo.strip(), area=area.strip(), nivel=nivel.strip(),
        bate_ponto=bate_ponto == "1",
        pct_adicional_25=float(pct_adicional_25 or 0),
        pct_he_sobre_25=float(pct_he_sobre_25 or 0),
        status=status, vigencia_inicio=vigencia_inicio or None,
        vigencia_fim=vigencia_fim or None,
    )
    if id.strip():
        db.execute(update(budget_cargos).where(budget_cargos.c.id == int(id)).values(**dados))
        msg = "Cargo atualizado."
    else:
        dados["criado_por"] = _usuario(request)
        db.execute(insert(budget_cargos).values(**dados))
        msg = "Cargo cadastrado."
    db.commit()
    return redirect_with_message("/folha/budget/cargos", success=msg)

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
def budget_vinculos_salvar(
    request: Request, db: Session = Depends(get_db),
    id: str = Form(""), codigo: str = Form(...), descricao: str = Form(""),
    tem_fgts: str = Form("0"), tem_inss_patronal: str = Form("0"),
    tem_decimo_terceiro: str = Form("0"), tem_ferias: str = Form("0"),
    tem_um_terco: str = Form("0"), tem_aviso_previo: str = Form("0"),
    tem_plr: str = Form("0"), pode_he: str = Form("0"), pode_beneficios: str = Form("0"),
    status: str = Form("Ativo"), vigencia_inicio: str = Form(""), vigencia_fim: str = Form(""),
):
    dados = dict(
        codigo=codigo.strip(), descricao=descricao.strip(),
        tem_fgts=tem_fgts == "1", tem_inss_patronal=tem_inss_patronal == "1",
        tem_decimo_terceiro=tem_decimo_terceiro == "1", tem_ferias=tem_ferias == "1",
        tem_um_terco=tem_um_terco == "1", tem_aviso_previo=tem_aviso_previo == "1",
        tem_plr=tem_plr == "1", pode_he=pode_he == "1", pode_beneficios=pode_beneficios == "1",
        status=status, vigencia_inicio=vigencia_inicio or None, vigencia_fim=vigencia_fim or None,
    )
    if id.strip():
        db.execute(update(budget_vinculos).where(budget_vinculos.c.id == int(id)).values(**dados))
        msg = "Vínculo atualizado."
    else:
        dados["criado_por"] = _usuario(request)
        db.execute(insert(budget_vinculos).values(**dados))
        msg = "Vínculo cadastrado."
    db.commit()
    return redirect_with_message("/folha/budget/vinculos", success=msg)

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
        "success": request.query_params.get("success"),
        "error": request.query_params.get("error"),
    })

@router.post("/folha/budget/verbas")
def budget_verbas_salvar(
    request: Request, db: Session = Depends(get_db),
    id: str = Form(""), codigo: str = Form(...), descricao: str = Form(...),
    categoria: str = Form("adicional"), tipo_calculo: str = Form("pct_salario"),
    base_calculo: str = Form(""), percentual: str = Form("0"),
    valor_fixo: str = Form("0"), quantidade_padrao: str = Form("0"),
    incide_inss: str = Form("0"), incide_fgts: str = Form("0"),
    incide_ferias: str = Form("0"), incide_decimo: str = Form("0"),
    empresa_codigo: str = Form(""), vinculo_codigo: str = Form(""),
    cargo_grupo: str = Form(""), prioridade: str = Form("99"),
    status: str = Form("Ativo"), vigencia_inicio: str = Form(""), vigencia_fim: str = Form(""),
):
    dados = dict(
        codigo=codigo.strip(), descricao=descricao.strip(),
        categoria=categoria, tipo_calculo=tipo_calculo, base_calculo=base_calculo.strip(),
        percentual=float(percentual or 0), valor_fixo=float(valor_fixo or 0),
        quantidade_padrao=float(quantidade_padrao or 0),
        incide_inss=incide_inss == "1", incide_fgts=incide_fgts == "1",
        incide_ferias=incide_ferias == "1", incide_decimo=incide_decimo == "1",
        empresa_codigo=empresa_codigo or None, vinculo_codigo=vinculo_codigo or None,
        cargo_grupo=cargo_grupo or None, prioridade=int(prioridade or 99),
        status=status, vigencia_inicio=vigencia_inicio or None, vigencia_fim=vigencia_fim or None,
    )
    if id.strip():
        db.execute(update(budget_verbas).where(budget_verbas.c.id == int(id)).values(**dados))
        msg = "Verba atualizada."
    else:
        dados["criado_por"] = _usuario(request)
        db.execute(insert(budget_verbas).values(**dados))
        msg = "Verba cadastrada."
    db.commit()
    return redirect_with_message("/folha/budget/verbas", success=msg)

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
def budget_beneficios_salvar(
    request: Request, db: Session = Depends(get_db),
    id: str = Form(""), codigo: str = Form(...), descricao: str = Form(...),
    empresa_codigo: str = Form(""), vinculo_codigo: str = Form(""), cargo_grupo: str = Form(""),
    valor_fixo: str = Form("0"), valor_unitario: str = Form("0"),
    quantidade: str = Form("0"), por_dependente: str = Form("0"),
    pct_empresa: str = Form("1"), status: str = Form("Ativo"),
    vigencia_inicio: str = Form(""), vigencia_fim: str = Form(""),
):
    dados = dict(
        codigo=codigo.strip(), descricao=descricao.strip(),
        empresa_codigo=empresa_codigo or None, vinculo_codigo=vinculo_codigo or None,
        cargo_grupo=cargo_grupo or None,
        valor_fixo=float(valor_fixo or 0), valor_unitario=float(valor_unitario or 0),
        quantidade=float(quantidade or 0), por_dependente=por_dependente == "1",
        pct_empresa=float(pct_empresa or 1),
        status=status, vigencia_inicio=vigencia_inicio or None, vigencia_fim=vigencia_fim or None,
    )
    if id.strip():
        db.execute(update(budget_beneficios).where(budget_beneficios.c.id == int(id)).values(**dados))
        msg = "Benefício atualizado."
    else:
        dados["criado_por"] = _usuario(request)
        db.execute(insert(budget_beneficios).values(**dados))
        msg = "Benefício cadastrado."
    db.commit()
    return redirect_with_message("/folha/budget/beneficios", success=msg)

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
        "success": request.query_params.get("success"),
        "error": request.query_params.get("error"),
    })

@router.post("/folha/budget/encargos")
def budget_encargos_salvar(
    request: Request, db: Session = Depends(get_db),
    id: str = Form(""), codigo: str = Form(...), descricao: str = Form(...),
    empresa_codigo: str = Form(""), vinculo_codigo: str = Form(""),
    percentual: str = Form("0"), divisor: str = Form("1"),
    verbas_base: str = Form(""), prioridade: str = Form("99"),
    status: str = Form("Ativo"), vigencia_inicio: str = Form(""), vigencia_fim: str = Form(""),
):
    dados = dict(
        codigo=codigo.strip(), descricao=descricao.strip(),
        empresa_codigo=empresa_codigo or None, vinculo_codigo=vinculo_codigo or None,
        percentual=float(percentual or 0), divisor=float(divisor or 1),
        verbas_base=verbas_base.strip() or None, prioridade=int(prioridade or 99),
        status=status, vigencia_inicio=vigencia_inicio or None, vigencia_fim=vigencia_fim or None,
    )
    if id.strip():
        db.execute(update(budget_encargos).where(budget_encargos.c.id == int(id)).values(**dados))
        msg = "Encargo atualizado."
    else:
        dados["criado_por"] = _usuario(request)
        db.execute(insert(budget_encargos).values(**dados))
        msg = "Encargo cadastrado."
    db.commit()
    return redirect_with_message("/folha/budget/encargos", success=msg)

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
):
    dados = dict(
        empresa_codigo=empresa_codigo or None, matricula=matricula.strip(),
        codigo_verba=codigo_verba.strip(), descricao_verba=descricao_verba.strip(),
        percentual=float(percentual) if percentual.strip() else None,
        valor=float(valor) if valor.strip() else None,
        quantidade=float(quantidade) if quantidade.strip() else None,
        justificativa=justificativa.strip() or None, prioridade=int(prioridade or 1),
        status=status, vigencia_inicio=vigencia_inicio or None, vigencia_fim=vigencia_fim or None,
    )
    if id.strip():
        db.execute(update(budget_excecoes).where(budget_excecoes.c.id == int(id)).values(**dados))
        msg = "Exceção atualizada."
    else:
        dados["criado_por"] = _usuario(request)
        db.execute(insert(budget_excecoes).values(**dados))
        msg = "Exceção cadastrada."
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

@router.get("/folha/budget/quantidades")
def budget_quantidades_list(request: Request, db: Session = Depends(get_db)):
    rows = db.execute(select(budget_quantidades).order_by(
        budget_quantidades.c.cenario, budget_quantidades.c.competencia, budget_quantidades.c.parametro
    )).mappings().all()
    cenarios = db.execute(select(budget_cenarios.c.nome).order_by(budget_cenarios.c.ordem)).scalars().all()
    empresas = db.execute(select(budget_empresas.c.codigo).order_by(budget_empresas.c.codigo)).scalars().all()
    return templates.TemplateResponse("folha/budget_quantidades.html", {
        "request": request, "rows": rows, "cenarios": cenarios, "empresas": empresas,
        "parametros": ["he_50", "he_100", "noturno", "he_sobre_25", "dias_vr"],
        "success": request.query_params.get("success"),
        "error": request.query_params.get("error"),
    })

@router.post("/folha/budget/quantidades")
def budget_quantidades_salvar(
    request: Request, db: Session = Depends(get_db),
    id: str = Form(""), cenario: str = Form(...), competencia: str = Form(...),
    parametro: str = Form(...), quantidade: str = Form("0"),
    empresa_codigo: str = Form(""), matricula: str = Form(""),
    codigo_cargo: str = Form(""), cargo_grupo: str = Form(""),
    centro_custo: str = Form(""), status: str = Form("Ativo"),
):
    dados = dict(
        cenario=cenario, competencia=competencia, parametro=parametro,
        quantidade=float(quantidade or 0),
        empresa_codigo=empresa_codigo or None, matricula=matricula or None,
        codigo_cargo=codigo_cargo or None, cargo_grupo=cargo_grupo or None,
        centro_custo=centro_custo or None, status=status,
    )
    if id.strip():
        db.execute(update(budget_quantidades).where(budget_quantidades.c.id == int(id)).values(**dados))
        msg = "Quantidade atualizada."
    else:
        dados["criado_por"] = _usuario(request)
        db.execute(insert(budget_quantidades).values(**dados))
        msg = "Quantidade cadastrada."
    db.commit()
    return redirect_with_message("/folha/budget/quantidades", success=msg)

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
    cenario: str = Form("Budget Original"),
    competencia: str = Form(...),
    id_arquivo: str = Form(""),
):
    from app.routers.folha_pagamento import folha_arquivos, folha_funcionarios, folha_rubricas

    # Apaga resultados anteriores do mesmo cenário+competência para reprocessar
    db.execute(
        delete(budget_resultado)
        .where(budget_resultado.c.cenario == cenario)
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
    cenario: str = "", competencia: str = "",
    empresa: str = "", matricula: str = "",
):
    from app.routers.folha_pagamento import folha_arquivos, folha_funcionarios

    cenarios = db.execute(select(budget_cenarios.c.nome).order_by(budget_cenarios.c.ordem)).scalars().all()
    competencias = db.execute(
        select(budget_resultado.c.competencia).distinct().order_by(budget_resultado.c.competencia)
    ).scalars().all()

    linhas = []
    totais: dict[str, float] = {}
    if cenario and competencia:
        q = (
            select(budget_resultado)
            .where(budget_resultado.c.cenario == cenario)
            .where(budget_resultado.c.competencia == competencia)
        )
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
        "cenarios": cenarios, "competencias": competencias,
        "sel_cenario": cenario, "sel_competencia": competencia,
        "sel_empresa": empresa, "sel_matricula": matricula,
        "success": request.query_params.get("success"),
        "error": request.query_params.get("error"),
    })
