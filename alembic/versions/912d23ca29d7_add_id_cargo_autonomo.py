"""add id cargo autonomo

Revision ID: 912d23ca29d7
Revises: 20260513_01
Create Date: 2026-05-13
"""

from alembic import op
import sqlalchemy as sa


revision = "912d23ca29d7"
down_revision = "20260513_01"
branch_labels = None
depends_on = None


def _has_table(bind, table_name):
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def _has_column(bind, table_name, column_name):
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return False
    return column_name in [c["name"] for c in inspector.get_columns(table_name)]


def upgrade():
    bind = op.get_bind()

    # 1. Criar tabela de cargos se não existir
    if not _has_table(bind, "dim_cargos_autonomos"):
        op.create_table(
            "dim_cargos_autonomos",
            sa.Column("id_cargo_autonomo", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("nome_cargo", sa.String(length=120), nullable=True),
            sa.Column("descricao", sa.Text(), nullable=True),
            sa.Column("status", sa.String(length=30), nullable=True),
        )

    # 2. Adicionar coluna em dim_autonomos se não existir
    if _has_table(bind, "dim_autonomos") and not _has_column(bind, "dim_autonomos", "id_cargo_autonomo"):
        op.add_column(
            "dim_autonomos",
            sa.Column("id_cargo_autonomo", sa.Integer(), nullable=True),
        )

    # 3. Popular cargos básicos
    bind.execute(sa.text("""
        INSERT INTO dim_cargos_autonomos (nome_cargo, descricao, status)
        SELECT 'Mecânico', 'Responsável pela parte mecânica do carro', 'Ativo'
        WHERE NOT EXISTS (
            SELECT 1 FROM dim_cargos_autonomos WHERE LOWER(TRIM(nome_cargo)) = LOWER(TRIM('Mecânico'))
        )
    """))

    bind.execute(sa.text("""
        INSERT INTO dim_cargos_autonomos (nome_cargo, descricao, status)
        SELECT 'Engenheiro', 'Responsável por setup, dados e telemetria', 'Ativo'
        WHERE NOT EXISTS (
            SELECT 1 FROM dim_cargos_autonomos WHERE LOWER(TRIM(nome_cargo)) = LOWER(TRIM('Engenheiro'))
        )
    """))

    bind.execute(sa.text("""
        INSERT INTO dim_cargos_autonomos (nome_cargo, descricao, status)
        SELECT 'Preparador', 'Responsável por preparação e apoio de box', 'Ativo'
        WHERE NOT EXISTS (
            SELECT 1 FROM dim_cargos_autonomos WHERE LOWER(TRIM(nome_cargo)) = LOWER(TRIM('Preparador'))
        )
    """))

    # 4. Preencher id_cargo_autonomo pelo tipo_autonomo
    if _has_table(bind, "dim_autonomos") and _has_column(bind, "dim_autonomos", "id_cargo_autonomo"):
        bind.execute(sa.text("""
            UPDATE dim_autonomos a
            SET id_cargo_autonomo = c.id_cargo_autonomo
            FROM dim_cargos_autonomos c
            WHERE LOWER(TRIM(COALESCE(a.tipo_autonomo, ''))) = LOWER(TRIM(COALESCE(c.nome_cargo, '')))
              AND a.id_cargo_autonomo IS NULL
        """))


def downgrade():
    bind = op.get_bind()

    if _has_table(bind, "dim_autonomos") and _has_column(bind, "dim_autonomos", "id_cargo_autonomo"):
        op.drop_column("dim_autonomos", "id_cargo_autonomo")

    # Não dropa dim_cargos_autonomos para evitar perda de cadastro manual.
