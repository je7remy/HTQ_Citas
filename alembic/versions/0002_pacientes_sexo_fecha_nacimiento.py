"""pacientes: agregar sexo y volver fecha_nacimiento NOT NULL

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-10

CONTEXTO: la versión inicial (0001) permitía fecha_nacimiento nullable
y no tenía campo sexo. Estos dos cambios vienen de la fase 2 del proyecto
cuando se decidió que los reportes demográficos del HTQPJB exigen ambos
campos.

Patrón usado: agregar con server_default temporal → rellenar datos
existentes → quitar default (sólo aplica a sexo).

OJO: el placeholder '1900-01-01' para fechas nulas es deliberadamente
absurdo para que el admin lo detecte a simple vista en la UI y lo
corrija. NO usar fechas plausibles como 1990-01-01.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Agregar columna `sexo` con default temporal "prefiero no decir"
    #    para los registros existentes. Después se elimina el server_default.
    op.add_column(
        "pacientes",
        sa.Column(
            "sexo",
            sa.String(length=20),
            nullable=False,
            server_default="prefiero no decir",
        ),
    )
    op.create_check_constraint(
        "ck_pacientes_sexo",
        "pacientes",
        "sexo IN ('masculino','femenino','otro','prefiero no decir')",
    )
    # Quitar el server_default para que las inserciones futuras requieran sexo explícito.
    op.alter_column("pacientes", "sexo", server_default=None)

    # 2. Volver fecha_nacimiento NOT NULL.
    #    Los registros existentes con fecha_nacimiento NULL reciben el placeholder
    #    1900-01-01. Es un valor de migración: el admin debe corregir esos
    #    registros manualmente desde la UI (queda visible como "01/01/1900").
    op.execute(
        "UPDATE pacientes SET fecha_nacimiento = '1900-01-01' "
        "WHERE fecha_nacimiento IS NULL"
    )
    op.alter_column(
        "pacientes",
        "fecha_nacimiento",
        existing_type=sa.Date(),
        nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "pacientes",
        "fecha_nacimiento",
        existing_type=sa.Date(),
        nullable=True,
    )
    op.drop_constraint("ck_pacientes_sexo", "pacientes", type_="check")
    op.drop_column("pacientes", "sexo")
