"""initial schema

Revision ID: 20260513_01
Revises:
Create Date: 2026-05-13 11:30:00
"""

from alembic import op

from app.database import Base
from app import models  # noqa: F401


# revision identifiers, used by Alembic.
revision = "20260513_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)

