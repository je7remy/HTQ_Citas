"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-04-11

Crea todas las tablas del Anexo D y el ÍNDICE ÚNICO PARCIAL en citas.

CONTEXTO HISTÓRICO: este archivo refleja el esquema tal como existía en
abril 2026, ANTES de los renombrados que hoy viven en init.sql:
  - hashed_password → password_hash
  - created_at → fecha_creacion / fecha_registro / fecha_hora
  - apellido → apellidos
  - registro_id → id_registro, ip → ip_origen (auditoria)
  - citas faltaba id_secretaria, fecha_registro
  - consultas tenía id_medico/id_paciente redundantes (vía cita)
  - pacientes tenía un campo email extra que se eliminó

Las migraciones 0002-0007 NO corrigen esos nombres. La sincronización
real entre Alembic y el esquema productivo se hace por el camino:
   1) `init.sql` corre al primer arranque y crea el esquema FINAL.
   2) `alembic stamp head` marca todas las revisiones como aplicadas.
Por eso `alembic upgrade head` desde 0 produce un esquema diferente al
de producción — NO usarlo sobre una BD vacía.

CUIDADO: si tocas este archivo, asegúrate de NO afectar el orden de
revisiones (revision/down_revision). Cambiarlos rompe la cadena.
"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- usuarios ---
    op.create_table(
        "usuarios",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("nombre", sa.String(length=100), nullable=False),
        sa.Column("email", sa.String(length=150), nullable=False),
        sa.Column("hashed_password", sa.String(), nullable=False),
        sa.Column("rol", sa.String(), nullable=False, server_default="secretaria"),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )

    # --- pacientes ---
    op.create_table(
        "pacientes",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("cedula", sa.String(length=11), nullable=False),
        sa.Column("nombre", sa.String(length=100), nullable=False),
        sa.Column("apellido", sa.String(length=100), nullable=False),
        sa.Column("fecha_nacimiento", sa.Date(), nullable=True),
        sa.Column("telefono", sa.String(length=20), nullable=True),
        sa.Column("email", sa.String(length=150), nullable=True),
        sa.Column("direccion", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cedula"),
    )

    # --- medicos ---
    op.create_table(
        "medicos",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("id_usuario", sa.Integer(), nullable=True),
        sa.Column("nombre", sa.String(length=100), nullable=False),
        sa.Column("especialidad", sa.String(length=100), nullable=False),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["id_usuario"], ["usuarios.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # --- horarios ---
    op.create_table(
        "horarios",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("id_medico", sa.Integer(), nullable=False),
        sa.Column("dia_semana", sa.Integer(), nullable=False),
        sa.Column("hora_inicio", sa.Time(), nullable=False),
        sa.Column("hora_fin", sa.Time(), nullable=False),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default="true"),
        sa.ForeignKeyConstraint(["id_medico"], ["medicos.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # --- citas ---
    op.create_table(
        "citas",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("id_paciente", sa.Integer(), nullable=False),
        sa.Column("id_medico", sa.Integer(), nullable=False),
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("hora", sa.Time(), nullable=False),
        sa.Column("motivo", sa.String(length=500), nullable=True),
        sa.Column("estado", sa.String(), nullable=False, server_default="programada"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["id_medico"], ["medicos.id"]),
        sa.ForeignKeyConstraint(["id_paciente"], ["pacientes.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # ÍNDICE ÚNICO PARCIAL — núcleo de la lógica anti-duplicados (Anexo D)
    # Solo en citas con estado != 'cancelada'. Permite reutilizar slot tras cancelación.
    #
    # POR QUÉ raw SQL en vez de sa.Index con `postgresql_where`: en la
    # versión de Alembic usada al escribir esta migración, autogenerate
    # no detectaba bien índices parciales. El raw SQL deja la intención
    # explícita y portátil al esquema de PostgreSQL.
    op.execute(
        """
        CREATE UNIQUE INDEX uq_citas_medico_fecha_hora
            ON citas (id_medico, fecha, hora)
            WHERE estado <> 'cancelada'
        """
    )

    # --- consultas ---
    op.create_table(
        "consultas",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("id_cita", sa.Integer(), nullable=False),
        sa.Column("id_medico", sa.Integer(), nullable=False),
        sa.Column("id_paciente", sa.Integer(), nullable=False),
        sa.Column("observaciones", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["id_cita"], ["citas.id"]),
        sa.ForeignKeyConstraint(["id_medico"], ["medicos.id"]),
        sa.ForeignKeyConstraint(["id_paciente"], ["pacientes.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # --- auditoria ---
    op.create_table(
        "auditoria",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("id_usuario", sa.Integer(), nullable=True),
        sa.Column("accion", sa.String(length=100), nullable=False),
        sa.Column("tabla_afectada", sa.String(length=100), nullable=False),
        sa.Column("registro_id", sa.Integer(), nullable=True),
        sa.Column("detalle", sa.String(), nullable=True),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["id_usuario"], ["usuarios.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("auditoria")
    op.drop_table("consultas")
    op.execute("DROP INDEX IF EXISTS uq_citas_medico_fecha_hora")
    op.drop_table("citas")
    op.drop_table("horarios")
    op.drop_table("medicos")
    op.drop_table("pacientes")
    op.drop_table("usuarios")
