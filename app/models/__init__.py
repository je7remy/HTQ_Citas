"""Modelos SQLModel del SGCM.

Esquema basado en el Anexo D de la tesis (DDL PostgreSQL).
Incluye la restricción central UNIQUE(id_medico, fecha, hora) en `citas`.
"""
from datetime import date, datetime, time
from enum import Enum
from typing import Optional

from sqlalchemy import CheckConstraint, Column, DateTime, Index, text
from sqlmodel import Field, Relationship, SQLModel

from app.core.datetime_utils import ahora_local


def _ts_column() -> Column:
    """Columna TIMESTAMPTZ NOT NULL — alineada con America/Santo_Domingo."""
    return Column(DateTime(timezone=True), nullable=False)


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


class SexoPaciente(str, Enum):
    masculino = "masculino"
    femenino = "femenino"
    otro = "otro"
    prefiero_no_decir = "prefiero no decir"


class TipoRespaldo(str, Enum):
    local = "local"
    externo = "externo"
    nube = "nube"


class ProveedorNube(str, Enum):
    s3 = "s3"
    gcs = "gcs"
    azure = "azure"


class EstadoRespaldo(str, Enum):
    en_progreso = "en_progreso"
    completado = "completado"
    fallido = "fallido"


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
    fecha_creacion: datetime = Field(default_factory=ahora_local, sa_column=_ts_column())


# ----------------------------- Pacientes -----------------------------
class Paciente(SQLModel, table=True):
    __tablename__ = "pacientes"
    __table_args__ = (
        CheckConstraint(
            "sexo IN ('masculino','femenino','otro','prefiero no decir')",
            name="ck_pacientes_sexo",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    cedula: str = Field(max_length=13, nullable=False, unique=True, index=True)
    nombre: str = Field(max_length=100, nullable=False)
    apellidos: str = Field(max_length=100, nullable=False)
    sexo: str = Field(max_length=20, nullable=False)
    fecha_nacimiento: date = Field(nullable=False)
    telefono: str = Field(max_length=15, nullable=False)
    direccion: Optional[str] = None
    fecha_registro: datetime = Field(default_factory=ahora_local, sa_column=_ts_column())


# ----------------------------- Médicos -----------------------------
class Medico(SQLModel, table=True):
    __tablename__ = "medicos"

    id: Optional[int] = Field(default=None, primary_key=True)
    id_usuario: Optional[int] = Field(default=None, foreign_key="usuarios.id")
    nombre: str = Field(max_length=100, nullable=False)
    especialidad: str = Field(max_length=50, nullable=False)
    especialidad_secundaria_1: Optional[str] = Field(default=None, max_length=50)
    especialidad_secundaria_2: Optional[str] = Field(default=None, max_length=50)
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
    fecha_registro: datetime = Field(default_factory=ahora_local, sa_column=_ts_column())


# ----------------------------- Consultas -----------------------------
class Consulta(SQLModel, table=True):
    __tablename__ = "consultas"

    id: Optional[int] = Field(default=None, primary_key=True)
    id_cita: int = Field(foreign_key="citas.id", nullable=False, unique=True)
    # Diagnóstico estructurado (Mejora 3.2)
    motivo_consulta: Optional[str] = None
    examen_fisico: Optional[str] = None
    condicion_principal: str = Field(nullable=False)
    condiciones_secundarias: Optional[str] = None
    tratamiento: Optional[str] = None
    # Campo legacy: se conserva para compatibilidad con datos pre-3.2
    observaciones: Optional[str] = None
    fecha_registro: datetime = Field(default_factory=ahora_local, sa_column=_ts_column())


# ----------------------------- Auditoría -----------------------------
class Auditoria(SQLModel, table=True):
    __tablename__ = "auditoria"

    id: Optional[int] = Field(default=None, primary_key=True)
    id_usuario: Optional[int] = Field(default=None, foreign_key="usuarios.id")
    nombre_usuario: str = Field(max_length=100, nullable=False)
    accion: AccionAuditoria = Field(nullable=False)
    tabla_afectada: str = Field(max_length=50, nullable=False)
    id_registro: Optional[int] = None
    detalle: Optional[str] = None
    fecha_hora: datetime = Field(default_factory=ahora_local, sa_column=_ts_column())
    ip_origen: Optional[str] = Field(default=None, max_length=45)


# ----------------------------- Especialidades -----------------------------
# Catálogo de especialidades médicas del HTQPJB (CU-17).
# La tabla actúa como tabla de referencia: el campo `medicos.especialidad`
# se sigue almacenando como string (sin FK), y el helper de validación
# del módulo de médicos consulta esta tabla en cada alta o edición.
# Decisión de diseño: no se introduce FK para minimizar el blast radius
# sobre los tests existentes y conservar retrocompatibilidad con datos
# pre-CU-17. La unicidad y el contenido del catálogo se garantizan a
# nivel BD (UNIQUE en nombre) y a nivel servicio (validación en backend).
class Especialidad(SQLModel, table=True):
    __tablename__ = "especialidades"

    id: Optional[int] = Field(default=None, primary_key=True)
    nombre: str = Field(max_length=50, nullable=False, unique=True, index=True)
    descripcion: Optional[str] = Field(default=None, max_length=200)
    activa: bool = Field(default=True, nullable=False)
    fecha_creacion: datetime = Field(default_factory=ahora_local, sa_column=_ts_column())


# ----------------------------- Respaldos -----------------------------
# Las columnas tipo/proveedor_nube/estado se almacenan como VARCHAR + CHECK
# (igual que rol en usuarios o estado en citas). Usar Enum Python aquí haría
# que SQLAlchemy intente crear tipos ENUM nativos en PostgreSQL al ejecutar
# create_all() sobre una BD con datos preexistentes — eso choca con init.sql
# (que define VARCHAR) y con la migración 0006 (que también es VARCHAR).
# Los enums viven solo en código de aplicación.
class Respaldo(SQLModel, table=True):
    __tablename__ = "respaldos"
    __table_args__ = (
        CheckConstraint(
            "tipo IN ('local','externo','nube')", name="ck_respaldos_tipo"
        ),
        CheckConstraint(
            "proveedor_nube IS NULL OR proveedor_nube IN ('s3','gcs','azure')",
            name="ck_respaldos_proveedor_nube",
        ),
        CheckConstraint(
            "estado IN ('en_progreso','completado','fallido')",
            name="ck_respaldos_estado",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    id_usuario: Optional[int] = Field(default=None, foreign_key="usuarios.id")
    nombre_usuario: str = Field(max_length=100, nullable=False)
    tipo: str = Field(max_length=20, nullable=False)
    proveedor_nube: Optional[str] = Field(default=None, max_length=20)
    ruta_origen: str = Field(nullable=False)
    ruta_destino: str = Field(nullable=False)
    tamano_bytes: int = Field(nullable=False)
    hash_sha256: str = Field(max_length=64, nullable=False)
    estado: str = Field(max_length=20, nullable=False)
    mensaje_error: Optional[str] = None
    fecha_inicio: datetime = Field(default_factory=ahora_local, sa_column=_ts_column())
    fecha_fin: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    duracion_segundos: Optional[int] = None
