from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text, Column, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class DimPiloto(Base):
    __tablename__ = "dim_pilotos"

    id_piloto: Mapped[int] = mapped_column(primary_key=True)
    nome_piloto: Mapped[str] = mapped_column(String(140), nullable=False)
    cpf: Mapped[str | None] = mapped_column(String(20))
    telefone: Mapped[str | None] = mapped_column(String(40))
    email: Mapped[str | None] = mapped_column(String(140))
    data_inclusao: Mapped[date] = mapped_column(Date, default=date.today, nullable=False)
    data_desligamento: Mapped[date | None] = mapped_column(Date)
    motivo_desligamento: Mapped[str | None] = mapped_column(String(255))
    status_piloto: Mapped[str] = mapped_column(String(30), default="Ativo", nullable=False)
    observacoes: Mapped[str | None] = mapped_column(Text)
    foto_url = Column(String)

    fatos = relationship("FatoPilotoAutonomoProva", back_populates="piloto")




class DimCargoAutonomo(Base):
    __tablename__ = "dim_cargos_autonomos"

    id_cargo_autonomo = Column(Integer, primary_key=True, index=True)
    nome_cargo = Column(String, nullable=False)
    descricao = Column(String)
    status = Column(String, default="Ativo")


class DimAutonomo(Base):
    __tablename__ = "dim_autonomos"

    id_autonomo: Mapped[int] = mapped_column(primary_key=True)
    nome_autonomo: Mapped[str] = mapped_column(String(140), nullable=False)
    cpf: Mapped[str | None] = mapped_column(String(20))
    telefone: Mapped[str | None] = mapped_column(String(40))
    email: Mapped[str | None] = mapped_column(String(140))
    tipo_autonomo: Mapped[str] = mapped_column(String(40), default="Mecanico", nullable=False)
    especialidade: Mapped[str | None] = mapped_column(String(120))
    data_inclusao: Mapped[date] = mapped_column(Date, default=date.today, nullable=False)
    data_saida: Mapped[date | None] = mapped_column(Date)
    motivo_saida: Mapped[str | None] = mapped_column(String(255))
    status_autonomo: Mapped[str] = mapped_column(String(30), default="Ativo", nullable=False)
    observacoes: Mapped[str | None] = mapped_column(Text)
    foto_url = Column(String)

fatos = relationship("FatoPilotoAutonomoProva", foreign_keys="FatoPilotoAutonomoProva.id_autonomo", back_populates="autonomo")


class DimEtapa(Base):
    __tablename__ = "dim_etapas"

    id_etapa: Mapped[int] = mapped_column(primary_key=True)
    temporada: Mapped[str] = mapped_column(String(20), nullable=False)
    nome_etapa: Mapped[str] = mapped_column(String(140), nullable=False)
    local: Mapped[str | None] = mapped_column(String(120))
    data_inicio: Mapped[date | None] = mapped_column(Date)
    data_fim: Mapped[date | None] = mapped_column(Date)
    status_etapa: Mapped[str] = mapped_column(String(30), default="Planejada", nullable=False)
    observacoes: Mapped[str | None] = mapped_column(Text)

    provas = relationship("DimProva", back_populates="etapa")
    fatos = relationship("FatoPilotoAutonomoProva", back_populates="etapa")


class DimTipoProva(Base):
    __tablename__ = "dim_tipos_categoria"

    id_tipo_prova: Mapped[int] = mapped_column(primary_key=True)
    nome_tipo_prova: Mapped[str] = mapped_column(String(80), nullable=False)
    descricao: Mapped[str | None] = mapped_column(Text)
    status_tipo_prova: Mapped[str] = mapped_column(String(30), default="Ativo", nullable=False)

    provas = relationship("DimProva", back_populates="tipo_prova")


class DimProva(Base):
    __tablename__ = "dim_categorias"

    id_prova: Mapped[int] = mapped_column(primary_key=True)
    id_etapa: Mapped[int] = mapped_column(ForeignKey("dim_etapas.id_etapa"), nullable=False)
    id_tipo_prova: Mapped[int] = mapped_column(ForeignKey("dim_tipos_categoria.id_tipo_prova"), nullable=False)
    nome_prova: Mapped[str] = mapped_column(String(140), nullable=False)
    data_prova: Mapped[date | None] = mapped_column(Date)
    status_prova: Mapped[str] = mapped_column(String(30), default="Planejada", nullable=False)
    observacoes: Mapped[str | None] = mapped_column(Text)

    etapa = relationship("DimEtapa", back_populates="provas")
    tipo_prova = relationship("DimTipoProva", back_populates="provas")
    fatos = relationship("FatoPilotoAutonomoProva", back_populates="prova")


class DimMotivoTroca(Base):
    __tablename__ = "dim_motivos_troca"

    id_motivo_troca: Mapped[int] = mapped_column(primary_key=True)
    motivo_troca: Mapped[str] = mapped_column(String(120), nullable=False)
    descricao: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="Ativo", nullable=False)


class DimStatusPagamento(Base):
    __tablename__ = "dim_status_pagamento"

    id_status_pagamento: Mapped[int] = mapped_column(primary_key=True)
    status_pagamento: Mapped[str] = mapped_column(String(40), nullable=False)


class FatoPilotoAutonomoProva(Base):
    __tablename__ = "fato_piloto_autonomo_prova"

    id_fato: Mapped[int] = mapped_column(primary_key=True)
    id_piloto: Mapped[int] = mapped_column(ForeignKey("dim_pilotos.id_piloto"), nullable=False)
    id_autonomo: Mapped[int] = mapped_column(ForeignKey("dim_autonomos.id_autonomo"), nullable=False)
    id_etapa: Mapped[int] = mapped_column(ForeignKey("dim_etapas.id_etapa"), nullable=False)
    id_prova: Mapped[int] = mapped_column(ForeignKey("dim_categorias.id_prova"), nullable=False)

    data_inicio_vinculo: Mapped[date] = mapped_column(Date, default=date.today, nullable=False)
    data_fim_vinculo: Mapped[date | None] = mapped_column(Date)
    status_vinculo: Mapped[str] = mapped_column(String(30), default="Ativo", nullable=False)

    foi_substituido: Mapped[str] = mapped_column(String(3), default="Nao", nullable=False)
    id_autonomo_substituto: Mapped[int | None] = mapped_column(ForeignKey("dim_autonomos.id_autonomo"))
    data_troca: Mapped[date | None] = mapped_column(Date)
    id_motivo_troca: Mapped[int | None] = mapped_column(ForeignKey("dim_motivos_troca.id_motivo_troca"))
    justificativa_troca: Mapped[str | None] = mapped_column(Text)

    nota_tecnica: Mapped[float | None] = mapped_column(Numeric(4, 2))
    nota_pontualidade: Mapped[float | None] = mapped_column(Numeric(4, 2))
    nota_comunicacao: Mapped[float | None] = mapped_column(Numeric(4, 2))
    nota_relacionamento: Mapped[float | None] = mapped_column(Numeric(4, 2))
    nota_geral: Mapped[float | None] = mapped_column(Numeric(4, 2))
    comentario_avaliacao: Mapped[str | None] = mapped_column(Text)
    link_avaliacao_externa = Column(String)
    data_avaliacao: Mapped[date | None] = mapped_column(Date)

    valor_fechado_etapa: Mapped[float | None] = mapped_column(Numeric(12, 2))
    dias_trabalhados: Mapped[int | None] = mapped_column(Integer)
    status_pagamento: Mapped[str | None] = mapped_column(String(40))
    data_pagamento: Mapped[date | None] = mapped_column(Date)
    documento: Mapped[str | None] = mapped_column(String(120))
    observacoes: Mapped[str | None] = mapped_column(Text)

    criado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    usuario_responsavel: Mapped[str | None] = mapped_column(String(120), default="admin.local")
    funcao_autonomo = Column(String)
    data_inicio_vinculo = Column(Date)
    data_fim_vinculo = Column(Date)
    status_vinculo = Column(String, default="Ativo")
    foi_substituido = Column(String, default="Não")
    id_autonomo_substituto = Column(Integer, ForeignKey("dim_autonomos.id_autonomo"))
    data_troca = Column(Date)
    id_motivo_troca = Column(Integer, ForeignKey("dim_motivos_troca.id_motivo_troca"))
    justificativa_troca = Column(String)
    valor_fechado_etapa = Column(Float)
    dias_trabalhados = Column(Integer)
    documento = Column(String)
    observacoes = Column(String)

    @property
    def valor_dia(self):
        if self.valor_fechado_etapa is None or not self.dias_trabalhados:
            return None
        return float(self.valor_fechado_etapa) / self.dias_trabalhados

    piloto = relationship("DimPiloto", foreign_keys=[id_piloto])
    autonomo = relationship("DimAutonomo", foreign_keys=[id_autonomo])
    autonomo_substituto = relationship("DimAutonomo", foreign_keys=[id_autonomo_substituto])
    etapa = relationship("DimEtapa", foreign_keys=[id_etapa])
    prova = relationship("DimProva", foreign_keys=[id_prova])
    motivo_troca = relationship("DimMotivoTroca", foreign_keys=[id_motivo_troca])

