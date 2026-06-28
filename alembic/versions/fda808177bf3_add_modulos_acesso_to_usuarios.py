"""add_modulos_acesso_to_usuarios

Revision ID: fda808177bf3
Revises: 912d23ca29d7
Create Date: 2026-06-17 14:19:28.882131
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = 'fda808177bf3'
down_revision = '912d23ca29d7'
branch_labels = None
depends_on = None


def column_exists(table, column):
    bind = op.get_bind()
    insp = inspect(bind)
    cols = [c["name"] for c in insp.get_columns(table)]
    return column in cols


def upgrade():
    if not column_exists("usuarios", "modulos_acesso"):
        op.add_column("usuarios", sa.Column("modulos_acesso", sa.Text(), nullable=True))


def downgrade():
    if column_exists("usuarios", "modulos_acesso"):
        op.drop_column("usuarios", "modulos_acesso")
