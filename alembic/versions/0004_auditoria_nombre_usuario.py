"""auditoria: agregar nombre_usuario denormalizado

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-10

CONTEXTO: descubrimos que cuando un usuario se desactivaba (soft delete)
y luego un admin consultaba la auditoría, el JOIN con `usuarios` perdía
ya el nombre en algunos casos (sobre todo si el usuario había sido
renombrado). La Ley 172-13 exige que la auditoría sea "inmutable" en
sentido pragmático — debe poder leerse aún sin la tabla de usuarios.

Solución: denormalizar el nombre del usuario en la fila de auditoría.
Rompe la 3FN deliberadamente para garantizar trazabilidad legal.

Patrón:
  1. Columna nullable temporalmente.
  2. UPDATE con JOIN para rellenar histórico desde usuarios.
  3. Placeholder '[usuario eliminado]' para huérfanos.
  4. ALTER a NOT NULL.

OJO: tras esta migración, TODO insert de auditoría debe rellenar
nombre_usuario (ver app/services/audit.py).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Agregar columna nullable inicialmente, para poder rellenar registros existentes.
    op.add_column(
        "auditoria",
        sa.Column("nombre_usuario", sa.String(length=100), nullable=True),
    )

    # 2. Poblar registros existentes con el nombre actual del usuario referenciado.
    op.execute(
        """
        UPDATE auditoria a
           SET nombre_usuario = COALESCE(u.nombre, '[usuario eliminado]')
          FROM (SELECT id, nombre FROM usuarios) u
         WHERE u.id = a.id_usuario
        """
    )
    # Para los registros con id_usuario NULL o usuario huérfano, asignar placeholder.
    op.execute(
        "UPDATE auditoria SET nombre_usuario = '[usuario eliminado]' "
        "WHERE nombre_usuario IS NULL"
    )

    # 3. Marcar la columna como NOT NULL.
    op.alter_column(
        "auditoria",
        "nombre_usuario",
        existing_type=sa.String(length=100),
        nullable=False,
    )


def downgrade() -> None:
    op.drop_column("auditoria", "nombre_usuario")
