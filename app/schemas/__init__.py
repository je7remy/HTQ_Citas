"""Schemas Pydantic (DTOs) — separados de los modelos ORM."""
from datetime import date, datetime, time
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models import EstadoCita, RolUsuario

SexoLiteral = Literal["masculino", "femenino", "otro", "prefiero no decir"]


# ============ Auth ============
class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    rol: RolUsuario
    nombre: str
    user_id: int


# ============ Usuario ============
class UsuarioCreate(BaseModel):
    nombre: str = Field(min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    rol: RolUsuario


class UsuarioRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    nombre: str
    email: EmailStr
    rol: RolUsuario
    activo: bool
    fecha_creacion: datetime


class UsuarioUpdate(BaseModel):
    nombre: Optional[str] = None
    activo: Optional[bool] = None
    rol: Optional[RolUsuario] = None


# ============ Paciente ============
class PacienteBase(BaseModel):
    cedula: str = Field(min_length=11, max_length=13)
    nombre: str = Field(min_length=2, max_length=100)
    apellidos: str = Field(min_length=2, max_length=100)
    sexo: SexoLiteral
    fecha_nacimiento: date
    telefono: str = Field(min_length=7, max_length=15)
    direccion: Optional[str] = None

    @field_validator("cedula")
    @classmethod
    def validar_cedula(cls, v: str) -> str:
        v = v.replace("-", "").strip()
        if not v.isdigit():
            raise ValueError("La cédula debe contener solo dígitos.")
        if len(v) != 11:
            raise ValueError("La cédula dominicana debe tener 11 dígitos.")
        return v


class PacienteCreate(PacienteBase):
    pass


class PacienteUpdate(BaseModel):
    nombre: Optional[str] = None
    apellidos: Optional[str] = None
    sexo: Optional[SexoLiteral] = None
    telefono: Optional[str] = None
    direccion: Optional[str] = None
    fecha_nacimiento: Optional[date] = None


class PacienteRead(PacienteBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    fecha_registro: datetime


# ============ Médico ============
class MedicoCreate(BaseModel):
    id_usuario: Optional[int] = None
    nombre: str = Field(min_length=2, max_length=100)
    especialidad: str = Field(min_length=2, max_length=50)
    especialidad_secundaria_1: Optional[str] = Field(default=None, max_length=50)
    especialidad_secundaria_2: Optional[str] = Field(default=None, max_length=50)
    telefono: Optional[str] = Field(default=None, max_length=15)


class MedicoUpdate(BaseModel):
    nombre: Optional[str] = None
    especialidad: Optional[str] = None
    especialidad_secundaria_1: Optional[str] = None
    especialidad_secundaria_2: Optional[str] = None
    telefono: Optional[str] = None
    activo: Optional[bool] = None


class MedicoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    id_usuario: Optional[int]
    nombre: str
    especialidad: str
    especialidad_secundaria_1: Optional[str] = None
    especialidad_secundaria_2: Optional[str] = None
    telefono: Optional[str]
    activo: bool


# ============ Horario ============
class HorarioCreate(BaseModel):
    id_medico: int
    dia_semana: int = Field(ge=1, le=7)
    hora_inicio: time
    hora_fin: time

    @field_validator("hora_fin")
    @classmethod
    def validar_rango(cls, v: time, info) -> time:
        inicio = info.data.get("hora_inicio")
        if inicio and v <= inicio:
            raise ValueError("hora_fin debe ser mayor que hora_inicio.")
        return v


class HorarioRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    id_medico: int
    dia_semana: int
    hora_inicio: time
    hora_fin: time
    activo: bool


# ============ Cita ============
class CitaCreate(BaseModel):
    id_paciente: int
    id_medico: int
    fecha: date
    hora: time
    motivo: Optional[str] = None


class CitaUpdate(BaseModel):
    fecha: Optional[date] = None
    hora: Optional[time] = None
    estado: Optional[EstadoCita] = None
    motivo: Optional[str] = None


class CitaRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    id_paciente: int
    id_medico: int
    fecha: date
    hora: time
    estado: EstadoCita
    motivo: Optional[str]
    id_secretaria: int
    fecha_registro: datetime


# ============ Consulta ============
class ConsultaCreate(BaseModel):
    id_cita: int
    motivo_consulta: Optional[str] = None
    examen_fisico: Optional[str] = None
    condicion_principal: str = Field(min_length=1, description="Diagnóstico principal")
    condiciones_secundarias: Optional[str] = None
    tratamiento: Optional[str] = None


class ConsultaRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    id_cita: int
    motivo_consulta: Optional[str] = None
    examen_fisico: Optional[str] = None
    condicion_principal: str
    condiciones_secundarias: Optional[str] = None
    tratamiento: Optional[str] = None
    observaciones: Optional[str] = None
    fecha_registro: datetime


# ============ Médico con Usuario (endpoint combinado) ============
class UsuarioMedicoPayload(BaseModel):
    nombre: str = Field(min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class MedicoSinUsuarioPayload(BaseModel):
    nombre: str = Field(min_length=2, max_length=100)
    especialidad: str = Field(min_length=2, max_length=50)
    especialidad_secundaria_1: Optional[str] = Field(default=None, max_length=50)
    especialidad_secundaria_2: Optional[str] = Field(default=None, max_length=50)
    telefono: Optional[str] = Field(default=None, max_length=15)


class MedicoConUsuarioCreate(BaseModel):
    usuario: UsuarioMedicoPayload
    medico: MedicoSinUsuarioPayload


# ============ Auditoría ============
class AuditoriaRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    id_usuario: Optional[int]
    nombre_usuario: str
    accion: str
    tabla_afectada: str
    id_registro: Optional[int]
    detalle: Optional[str]
    fecha_hora: datetime
    ip_origen: Optional[str]


class AuditoriaPage(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[AuditoriaRead]


# ============ Reportes administrativos ============
class RolStats(BaseModel):
    total: int
    activos: int
    inactivos: int


class UsuariosResumen(BaseModel):
    total_usuarios: int
    por_rol: dict[str, dict[str, int]]
    fecha_generacion: datetime


class MedicoDetalleStats(BaseModel):
    id: int
    nombre: str
    especialidad: str
    especialidades_secundarias: list[str]
    total_citas: int
    total_consultas: int
    citas_atendidas: int
    citas_canceladas: int
    citas_pendientes: int
    tasa_atendidas: float
    tasa_canceladas: float
    dias_disponibilidad: int


class MedicosDetalleResponse(BaseModel):
    total_medicos: int
    medicos: list[MedicoDetalleStats]
    fecha_generacion: datetime
