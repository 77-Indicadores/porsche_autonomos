"""add config_sistema and facilities_complementos

Revision ID: 7176c77dfe42
Revises: fda808177bf3
Create Date: 2026-07-01 10:13:50.439557
"""

from alembic import op
import sqlalchemy as sa



# revision identifiers, used by Alembic.
revision = '7176c77dfe42'
down_revision = 'fda808177bf3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'config_sistema',
        sa.Column('chave', sa.String(length=120), nullable=False),
        sa.Column('valor', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('chave'),
    )
    op.create_table(
        'facilities_complementos',
        sa.Column('source_row', sa.String(length=20), nullable=False),
        sa.Column('area_servico', sa.String(length=255), nullable=True),
        sa.Column('unidade_local', sa.String(length=255), nullable=True),
        sa.Column('tipo_atendimento', sa.String(length=255), nullable=True),
        sa.Column('data_inicio', sa.String(length=20), nullable=True),
        sa.Column('data_finalizacao', sa.String(length=20), nullable=True),
        sa.Column('dentro_prazo', sa.String(length=10), nullable=True),
        sa.Column('retrabalho', sa.String(length=10), nullable=True),
        sa.Column('custo', sa.String(length=50), nullable=True),
        sa.Column('observacao', sa.Text(), nullable=True),
        sa.Column('rastreamento', sa.String(length=255), nullable=True),
        sa.Column('atualizado_em', sa.String(length=30), nullable=True),
        sa.PrimaryKeyConstraint('source_row'),
    )


def downgrade() -> None:
    op.drop_table('facilities_complementos')
    op.drop_table('config_sistema')

