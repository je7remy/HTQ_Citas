"""medicos: agregar especialidades secundarias 1 y 2

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-10
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "medicos",
        sa.Column("especialidad_secundaria_1", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "medicos",
        sa.Column("especialidad_secundaria_2", sa.String(length=50), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("medicos", "especialidad_secundaria_2")
    op.drop_column("medicos", "especialidad_secundaria_1")
