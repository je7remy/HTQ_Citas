"""consultas: diagnóstico estructurado (5 campos)

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-10

CONTEXTO (Mejora 3.2 de la tesis): originalmente el médico registraba
TODO en un único campo `observaciones` (texto libre). Esto hacía
imposible:
  - Generar reportes por diagnóstico CIE-10.
  - Buscar pacientes por condición principal.
  - Imprimir un PDF clínico estructurado.

Estrategia de migración:
  1. Agregar 5 columnas nullable.
  2. Mover `observaciones` viejo → `motivo_consulta` (lo que más se
     parece semánticamente — qué dijo el paciente al entrar).
  3. Marcar `condicion_principal` con placeholder explícito en datos
     legacy: "(no registrado en formato anterior)" para que sea visible
     en historial y el médico pueda actualizarlo si necesita.
  4. Conservar `observaciones` como nullable para no perder nada.

OJO: el campo `observaciones` NO se elimina. Sigue ahí para datos
históricos. La UI moderna usa los 5 campos estructurados; la consulta
de historial muestra `observaciones` SOLO si los otros están vacíos.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Agregar columnas nuevas como nullable
    op.add_column("consultas", sa.Column("motivo_consulta", sa.Text(), nullable=True))
    op.add_column("consultas", sa.Column("examen_fisico", sa.Text(), nullable=True))
    op.add_column("consultas", sa.Column("condicion_principal", sa.Text(), nullable=True))
    op.add_column("consultas", sa.Column("condiciones_secundarias", sa.Text(), nullable=True))
    op.add_column("consultas", sa.Column("tratamiento", sa.Text(), nullable=True))

    # Migrar datos existentes:
    #   observaciones (legacy) → motivo_consulta
    #   condicion_principal → placeholder con marca de migración
    op.execute("UPDATE consultas SET motivo_consulta = observaciones WHERE observaciones IS NOT NULL")
    op.execute(
        "UPDATE consultas SET condicion_principal = '(no registrado en formato anterior)' "
        "WHERE condicion_principal IS NULL"
    )

    # Volver observaciones nullable y condicion_principal NOT NULL
    op.alter_column(
        "consultas", "observaciones",
        existing_type=sa.Text(),
        nullable=True,
    )
    op.alter_column(
        "consultas", "condicion_principal",
        existing_type=sa.Text(),
        nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "consultas", "observaciones",
        existing_type=sa.Text(),
        nullable=False,
    )
    op.drop_column("consultas", "tratamiento")
    op.drop_column("consultas", "condiciones_secundarias")
    op.drop_column("consultas", "condicion_principal")
    op.drop_column("consultas", "examen_fisico")
    op.drop_column("consultas", "motivo_consulta")
