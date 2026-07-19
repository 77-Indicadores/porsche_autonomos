"""Parser de PDFs de extrato mensal de folha de pagamento (Datamétodo/Domínio).

Estrutura do PDF:
- Cabeçalho por página: Empresa, CNPJ, Cálculo, Competência, Emissão.
- Blocos por empregado: linha "Empr.:", "Vínculo:", "Cargo:", rubricas em duas
  colunas (proventos à esquerda, descontos à direita, sufixo P/D), linha de
  totais "ND:" e bases "NF:".
- Seções "Resumo por Rubrica", "INSS FGTS, PIS e ISS" e "Situações" são
  resumos gerais e não geram funcionários.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

import pdfplumber

# Divisa entre a coluna de proventos (esquerda) e descontos (direita).
COLUNA_DIREITA_X = 298.0
# Distância mínima entre caracteres para considerar quebra de palavra
# (o código da rubrica vem "colado" na descrição, sem caractere de espaço).
GAP_PALAVRA = 1.8

# Uma linha de rubricas contém até duas colunas: provento (P) à esquerda e
# desconto (D) à direita. Extraímos ambas com findall na linha inteira, sem
# depender de corte fixo de coluna (que cortava o sufixo P/D de valores longos).
RE_RUBRICA = re.compile(
    r"(\d{2,5})\s+(.+?)\s+([\d.,]+)\s+([\d.,]+)\s*([PD])(?=\s|$)"
)
# A matrícula pode vir colada ao nome ("399CAIO") e o nome pode colar em
# "Situação" quando atinge a margem ("OLIVEIRASituação"); por isso \s* antes de Situa.
RE_EMPREGADO = re.compile(
    r"^Empr\.?:?\s*(\d+)\s*([^\d].*?)\s*Situa\S+:\s+(.+?)\s+CPF:\s*([\d.\-]*)\s*Adm:\s*([\d/]*)$"
)
RE_VINCULO = re.compile(
    r"^V\S+nculo:\s*(.*?)\s*CC:\s*(\S*)\s*Depto:\s*(\S*)\s*Horas\s+M\S+s:\s*([\d.,]*)$"
)
RE_CARGO = re.compile(
    r"^Cargo:\s*(\d*)\s*(.*?)\s+Filial:\s*(\S*)\s+Sal\S+rio:\s*([\d.,]*)$"
)
RE_TOTAIS = re.compile(
    r"^ND:\s*(\d+)\s+Proventos:\s*([\d.,]+)\s+Descontos:\s*([\d.,]+).*?L\S+quido:\s*([\d.,-]+)$"
)
RE_BASES = re.compile(
    r"^NF:\s*\S+\s+Base\s+INSS:\s*([\d.,]+)\s*Excedente\s+INSS:\s*([\d.,]+)\s+"
    r"Base\s+FGTS:\s*([\d.,]+)\s+Valor\s+FGTS:\s*([\d.,]+)\s+Base\s+IRRF:\s*([\d.,-]+)$"
)


def _parse_valor(texto: str | None) -> Decimal | None:
    if not texto:
        return None
    normalizado = texto.strip().replace(".", "").replace(",", ".")
    try:
        return Decimal(normalizado)
    except InvalidOperation:
        return None


@dataclass
class RubricaExtraida:
    codigo: str
    descricao: str
    referencia: Decimal | None
    valor: Decimal | None
    tipo: str  # "P" provento, "D" desconto


@dataclass
class FuncionarioExtraido:
    matricula: str
    nome: str
    pagina: int | None = None
    situacao: str = ""
    cpf: str = ""
    data_admissao: str = ""
    vinculo: str = ""
    centro_custo: str = ""
    departamento: str = ""
    horas_mes: Decimal | None = None
    codigo_cargo: str = ""
    cargo: str = ""
    cbo: str = ""
    filial: str = ""
    salario: Decimal | None = None
    nd: int = 0
    total_proventos: Decimal | None = None
    total_descontos: Decimal | None = None
    liquido: Decimal | None = None
    base_inss: Decimal | None = None
    base_fgts: Decimal | None = None
    valor_fgts: Decimal | None = None
    base_irrf: Decimal | None = None
    observacao: str = ""
    competencia: str = ""
    tipo_calculo: str = ""
    rubricas: list[RubricaExtraida] = field(default_factory=list)


@dataclass
class FolhaExtraida:
    empresa_codigo: str = ""
    empresa_nome: str = ""
    cnpj: str = ""
    data_emissao: str = ""
    competencias: list[str] = field(default_factory=list)
    tipos_calculo: list[str] = field(default_factory=list)
    funcionarios: list[FuncionarioExtraido] = field(default_factory=list)

    @property
    def competencia_resumo(self) -> str:
        if not self.competencias:
            return ""
        if len(self.competencias) == 1:
            return self.competencias[0]
        return f"{self.competencias[0]} a {self.competencias[-1]}"

    @property
    def total_proventos(self) -> Decimal:
        return sum((f.total_proventos or Decimal(0) for f in self.funcionarios), Decimal(0))

    @property
    def total_descontos(self) -> Decimal:
        return sum((f.total_descontos or Decimal(0) for f in self.funcionarios), Decimal(0))

    @property
    def total_liquido(self) -> Decimal:
        return sum((f.liquido or Decimal(0) for f in self.funcionarios), Decimal(0))


def _linhas_da_pagina(page) -> list[list[dict]]:
    """Agrupa caracteres em linhas visuais (tolerância vertical de 2.5pt)."""
    chars = sorted(page.chars, key=lambda c: (c["top"], c["x0"]))
    linhas: list[list[dict]] = []
    atual: list[dict] = []
    topo_atual: float | None = None
    for c in chars:
        if topo_atual is None or abs(c["top"] - topo_atual) <= 2.5:
            atual.append(c)
            topo_atual = c["top"] if topo_atual is None else min(topo_atual, c["top"])
        else:
            linhas.append(atual)
            atual = [c]
            topo_atual = c["top"]
    if atual:
        linhas.append(atual)
    return linhas


def _texto_coluna(chars: list[dict]) -> str:
    """Reconstrói o texto de uma coluna inserindo espaço em lacunas visuais."""
    chars = sorted(chars, key=lambda c: c["x0"])
    partes: list[str] = []
    anterior = None
    for c in chars:
        if anterior is not None and (c["x0"] - anterior["x1"]) > GAP_PALAVRA:
            partes.append(" ")
        partes.append(c["text"])
        anterior = c
    texto = "".join(partes)
    return re.sub(r"\s+", " ", texto).strip()


def _extrair_rubricas(texto: str) -> list[RubricaExtraida]:
    rubricas: list[RubricaExtraida] = []
    for codigo, descricao, referencia, valor, tipo in RE_RUBRICA.findall(texto):
        rubricas.append(
            RubricaExtraida(
                codigo=codigo,
                descricao=descricao.strip(),
                referencia=_parse_valor(referencia),
                valor=_parse_valor(valor),
                tipo=tipo,
            )
        )
    return rubricas


def parse_folha_pdf(conteudo: bytes) -> FolhaExtraida:
    folha = FolhaExtraida()
    funcionario: FuncionarioExtraido | None = None
    em_resumo = False

    with pdfplumber.open(io.BytesIO(conteudo)) as pdf:
        for numero_pagina, page in enumerate(pdf.pages, start=1):
            competencia_pagina = ""
            calculo_pagina = ""
            for linha in _linhas_da_pagina(page):
                esquerda = [c for c in linha if c["x0"] < COLUNA_DIREITA_X]
                direita = [c for c in linha if c["x0"] >= COLUNA_DIREITA_X]
                texto = _texto_coluna(linha)
                texto_esq = _texto_coluna(esquerda)
                texto_dir = _texto_coluna(direita)

                if not texto:
                    continue

                if texto_esq.startswith("Empresa:"):
                    m = re.match(r"^Empresa:\s*(\d+)\s*-\s*(.+)$", texto_esq)
                    if m and not folha.empresa_codigo:
                        folha.empresa_codigo = m.group(1)
                        folha.empresa_nome = m.group(2).strip().rstrip(".")
                    continue
                if texto_esq.startswith("CNPJ:"):
                    if not folha.cnpj:
                        folha.cnpj = texto_esq.split(":", 1)[1].strip()
                    m = re.search(r"Emiss\S+o:\s*([\d/]+)", texto_dir)
                    if m and not folha.data_emissao:
                        folha.data_emissao = m.group(1)
                    continue
                if re.match(r"^C\S+lculo:", texto_esq):
                    calculo_pagina = texto_esq.split(":", 1)[1].strip()
                    if calculo_pagina and calculo_pagina not in folha.tipos_calculo:
                        folha.tipos_calculo.append(calculo_pagina)
                    continue
                if re.match(r"^Compet\S+ncia:", texto_esq):
                    competencia_pagina = texto_esq.split(":", 1)[1].strip()
                    if competencia_pagina and competencia_pagina not in folha.competencias:
                        folha.competencias.append(competencia_pagina)
                    continue

                # Seções de resumo geral: ignora até o próximo empregado.
                if texto.startswith("Resumo por Rubrica") or texto.startswith("INSS FGTS"):
                    em_resumo = True
                    funcionario = None
                    continue

                m = RE_EMPREGADO.match(texto)
                if m:
                    em_resumo = False
                    funcionario = FuncionarioExtraido(
                        matricula=m.group(1),
                        nome=m.group(2).strip(),
                        pagina=numero_pagina,
                        situacao=m.group(3).strip(),
                        cpf=m.group(4).strip(),
                        data_admissao=m.group(5).strip(),
                        competencia=competencia_pagina,
                        tipo_calculo=calculo_pagina,
                    )
                    folha.funcionarios.append(funcionario)
                    continue

                if em_resumo or funcionario is None:
                    continue

                m = RE_VINCULO.match(texto)
                if m:
                    if not funcionario.vinculo:
                        funcionario.vinculo = m.group(1).strip()
                        funcionario.centro_custo = m.group(2).strip()
                        funcionario.departamento = m.group(3).strip()
                        funcionario.horas_mes = _parse_valor(m.group(4))
                    continue

                m = RE_CARGO.match(texto)
                if m:
                    # Só registra o primeiro cargo (quando há múltiplos vínculos no mesmo extrato,
                    # como estagiária + autônomo + sócio, mantemos o principal que vem primeiro)
                    if not funcionario.codigo_cargo:
                        cargo_raw = m.group(2).strip()
                        # Remove CBO glued to end of cargo name
                        cargo_raw = re.sub(r'C[\w.]*B[\w.]*O[\w.:]*\s+\S*\d{4,}\s*$', '', cargo_raw)
                        cargo_raw = re.sub(r'\s+C\.B\.O[.:].*$', '', cargo_raw)
                        funcionario.codigo_cargo = (m.group(1) or "").strip()
                        funcionario.cargo = cargo_raw.strip()
                        funcionario.cbo = ""
                        funcionario.filial = m.group(3).strip()
                        funcionario.salario = _parse_valor(m.group(4))
                    continue

                m = RE_TOTAIS.match(texto)
                if m:
                    # Um funcionário pode ter mais de um cálculo no mesmo bloco
                    # (folha + adiantamento/férias), cada um com sua linha "ND".
                    # Acumulamos para bater com o Total Geral do extrato.
                    funcionario.nd = max(funcionario.nd or 0, int(m.group(1) or 0))
                    prov = _parse_valor(m.group(2)) or Decimal(0)
                    desc = _parse_valor(m.group(3)) or Decimal(0)
                    liq = _parse_valor(m.group(4)) or Decimal(0)
                    funcionario.total_proventos = (funcionario.total_proventos or Decimal(0)) + prov
                    funcionario.total_descontos = (funcionario.total_descontos or Decimal(0)) + desc
                    funcionario.liquido = (funcionario.liquido or Decimal(0)) + liq
                    continue

                m = RE_BASES.match(texto)
                if m:
                    funcionario.base_inss = _parse_valor(m.group(1))
                    funcionario.base_fgts = _parse_valor(m.group(3))
                    funcionario.valor_fgts = _parse_valor(m.group(4))
                    funcionario.base_irrf = _parse_valor(m.group(5))
                    # Bases encerram o bloco do empregado; linhas seguintes até o
                    # próximo "Empr.:" podem ser observações (ex.: "FERIAS DE ...").
                    continue

                rubricas = _extrair_rubricas(texto)
                if rubricas:
                    funcionario.rubricas.extend(rubricas)
                    continue

                # Observações do bloco (ex.: período de férias).
                if funcionario.base_inss is not None and re.match(r"^[A-ZÀ-Ü]", texto_esq or ""):
                    # Acentos podem vir corrompidos pela fonte do PDF, por isso o \S no lugar de "í".
                    if not re.match(r"^(Total Geral|L\S?quido|Sistema licenciado|EXTRATO)", texto_esq):
                        funcionario.observacao = (
                            f"{funcionario.observacao}; {texto_esq}" if funcionario.observacao else texto_esq
                        )

    return folha
