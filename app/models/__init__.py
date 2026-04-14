"""Modelos SQLModel del SGCM.

Esquema basado en el Anexo D de la tesis (DDL PostgreSQL).
Incluye la restricción central UNIQUE(id_medico, fecha, hora) en `citas`.
"""
from datetime import date, datetime, time
from enum import Enum
from typing import Optional

from sqlalchemy import CheckConstraint, Index, text
from sqlmodel import Field, Relationship, SQLModel


# ----------------------------- Enums -----------------------------
class RolUsuario(str, Enum):
    secretaria = "secretaria"
    medico = "medico"
    admin = "admin"


class EstadoCita(str, Enum):
    pendiente = "pendiente"
    atendida = "atendida"
    cancelada = "cancelada"


class AccionAuditoria(str, Enum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    LOGIN = "LOGIN"


# ----------------------------- Usuarios -----------------------------
class Usuario(SQLModel, table=True):
    __tablename__ = "usuarios"
    __table_args__ = (
        CheckConstraint("rol IN ('secretaria','medico','admin')", name="ck_usuarios_rol"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    nombre: str = Field(max_length=100, nullable=False)
    email: str = Field(max_length=100, nullable=False, unique=True, index=True)
    password_hash: str = Field(max_length=255, nullable=False)
    rol: RolUsuario = Field(nullable=False)
    activo: bool = Field(default=True)
    fecha_creacion: datetime = Field(default_factory=datetime.utcnow)


# ----------------------------- Pacientes -----------------------------
class Paciente(SQLModel, table=True):
    __tablename__ = "pacientes"

    id: Optional[int] = Field(default=None, primary_key=True)
    cedula: str = Field(max_length=13, nullable=False, unique=True, index=True)
    nombre: str = Field(max_length=100, nullable=False)
    apellidos: str = Field(max_length=100, nullable=False)
    fecha_nacimiento: Optional[date] = None
    telefono: str = Field(max_length=15, nullable=False)
    direccion: Optional[str] = None
    fecha_registro: datetime = Field(default_factory=datetime.utcnow)


# ----------------------------- Médicos -----------------------------
class Medico(SQLModel, table=True):
    __tablename__ = "medicos"

    id: Optional[int] = Field(default=None, primary_key=True)
    id_usuario: Optional[int] = Field(default=None, foreign_key="usuarios.id")
    nombre: str = Field(max_length=100, nullable=False)
    especialidad: str = Field(max_length=50, nullable=False)
    telefono: Optional[str] = Field(default=None, max_length=15)
    activo: bool = Field(default=True)

    horarios: list["Horario"] = Relationship(back_populates="medico")


# ----------------------------- Horarios -----------------------------
class Horario(SQLModel, table=True):
    __tablename__ = "horarios"
    __table_args__ = (
        CheckConstraint("dia_semana BETWEEN 1 AND 7", name="ck_horarios_dia"),
        CheckConstraint("hora_inicio < hora_fin", name="ck_horarios_rango"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    id_medico: int = Field(foreign_key="medicos.id", nullable=False)
    dia_semana: int = Field(nullable=False, description="1=Lunes ... 7=Domingo")
    hora_inicio: time = Field(nullable=False)
    hora_fin: time = Field(nullable=False)
    activo: bool = Field(default=True)

    medico: Optional[Medico] = Relationship(back_populates="horarios")


# ----------------------------- Citas -----------------------------
class Cita(SQLModel, table=True):
    __tablename__ = "citas"
    __table_args__ = (
        # Índice único PARCIAL: garantiza unicidad de (medico, fecha, hora)
        # SOLO para citas no canceladas. Esto cumple a la vez:
        #  - Anexo D de la tesis: la restricción anti-duplicados sigue activa.
        #  - CU-07/CU-08 y P2.4: cancelar/reprogramar libera el horario.
        # PostgreSQL soporta esto nativamente con índice parcial (WHERE).
        Index(
            "uq_citas_medico_fecha_hora",
            "id_medico",
            "fecha",
            "hora",
            unique=True,
            postgresql_where=text("estado <> 'cancelada'"),
            sqlite_where=text("estado <> 'cancelada'"),
        ),
        CheckConstraint(
            "estado IN ('pendiente','atendida','cancelada')", name="ck_citas_estado"
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    id_paciente: int = Field(foreign_key="pacientes.id", nullable=False)
    id_medico: int = Field(foreign_key="medicos.id", nullable=False, index=True)
    fecha: date = Field(nullable=False, index=True)
    hora: time = Field(nullable=False)
    estado: EstadoCita = Field(default=EstadoCita.pendiente)
    motivo: Optional[str] = None
    id_secretaria: int = Field(foreign_key="usuarios.id", nullable=False)
    fecha_registro: datetime = Field(default_factory=datetime.utcnow)


# ----------------------------- Consultas -----------------------------
class Consulta(SQLModel, table=True):
    __tablename__ = "consultas"

    id: Optional[int] = Field(default=None, primary_key=True)
    id_cita: int = Field(foreign_key="citas.id", nullable=False, unique=True)
    observaciones: str = Field(nullable=False)
    fecha_registro: datetime = Field(default_factory=datetime.utcnow)


# ----------------------------- Auditoría -----------------------------
class Auditoria(SQLModel, table=True):
    __tablename__ = "auditoria"

    id: Optional[int] = Field(default=None, primary_key=True)
    id_usuario: Optional[int] = Field(default=None, foreign_key="usuarios.id")
    accion: AccionAuditoria = Field(nullable=False)
    tabla_afectada: str = Field(max_length=50, nullable=False)
    id_registro: Optional[int] = None
    detalle: Optional[str] = None
    fecha_hora: datetime = Field(default_factory=datetime.utcnow)
    ip_origen: Optional[str] = Field(default=None, max_length=45)
