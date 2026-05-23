"""Schemas Pydantic (DTOs) — separados de los modelos ORM.

CONTEXTO: SQLModel permite usar la misma clase para ORM y validación de
entrada/salida, PERO mezclar ambas responsabilidades trae problemas:
- Exposición accidental de campos sensibles (password_hash) si la API
  serializa un modelo entero.
- Validaciones de entrada (rangos, min_length) que no aplican al guardar
  en BD pero sí al recibir del cliente.
- Cambios en el esquema de BD que no deberían romper el contrato HTTP.
Por eso TODO endpoint trabaja con un schema de este archivo, nunca con
el modelo SQLModel directo.

Convención de naming:
  XxxCreate  → payload de POST (datos para crear)
  XxxUpdate  → payload de PATCH/PUT (todos opcionales)
  XxxRead    → respuesta GET (incluye id y campos calculados/timestamps)
  XxxBase    → mixin compartido entre Create y Read (validadores comunes)

OJO: si añades un campo nuevo a un modelo, también hay que exponerlo o
filtrarlo aquí. No es automático.
"""
from datetime import date, datetime, time
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models import EstadoCita, RolUsuario

SexoLiteral = Literal["masculino", "femenino", "otro", "prefiero no decir"]


# ============ Auth ============
# OJO: min_length=6 acá es a propósito menos estricto que el min_length=8
# de UsuarioCreate. Razón: hay credenciales legacy en producción con 6-7
# caracteres y rechazar el login bloquearía a esos usuarios. La política
# fuerte (8+) aplica al CREAR cuenta nueva, no al hacer login.
class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)


# Lo que devuelve POST /auth/login. El frontend guarda `access_token`
# en sessionStorage; `rol` y `nombre` se usan para pintar la UI sin
# tener que decodificar el JWT en cliente; `user_id` se usa en filtros
# como "mis citas" cuando el rol es médico.
class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    rol: RolUsuario
    nombre: str
    user_id: int


# ============ Usuario ============
# IMPORTANTE: la política de 8+ caracteres aplica al CREAR/CAMBIAR. Es
# el mínimo razonable para una cuenta nueva en un sistema con datos
# sensibles. El hash se hace en el endpoint, NUNCA aquí — los schemas
# no deben tocar bcrypt.
class UsuarioCreate(BaseModel):
    nombre: str = Field(min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    rol: RolUsuario


# Nótese la ausencia deliberada de `password_hash`: este DTO se devuelve
# al cliente y filtrar el hash sería un escape de información, aunque
# bcrypt sea costoso de revertir.
class UsuarioRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    nombre: str
    email: EmailStr
    rol: RolUsuario
    activo: bool
    fecha_creacion: datetime


# El email NO se permite cambiar por PATCH — es identificador estable
# y cambiarlo rompería el JWT vigente del usuario. Si hace falta cambiar
# el email se crea un usuario nuevo y se desactiva el anterior.
class UsuarioUpdate(BaseModel):
    nombre: Optional[str] = None
    activo: Optional[bool] = None
    rol: Optional[RolUsuario] = None


# Endpoint separado para reset de password (admin) — la misma política
# de 8+ caracteres que UsuarioCreate.
class PasswordReset(BaseModel):
    nueva_password: str = Field(min_length=8, max_length=128)


# ============ Paciente ============
# Validador de cédula: tolera entrada con guiones (xxx-xxxxxxx-x) pero
# almacena sólo los 11 dígitos. NO valida el dígito verificador acá —
# se aceptan cédulas de prueba en seed que pueden no cumplirlo. La
# validación módulo-10 vive en app/db/seed.cedula_dominicana_es_valida
# para uso interno, no como filtro de entrada.
#
# OJO: si se decide endurecer y exigir cédula real con dígito válido,
# habría que migrar primero los datos existentes — el seed pasa por su
# propio generador, pero datos importados manualmente podrían fallar.
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
        # Normalizamos: cualquier guión que venga del frontend o de
        # import manual se elimina. Lo que se guarda en BD son SIEMPRE
        # 11 dígitos pelados — el UNIQUE de la BD se basa en esa forma.
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
# `dia_semana` ge=1 le=7 con convención ISO (1=Lunes, 7=Domingo) — igual
# que en el modelo Horario. Cambiar la convención (ej. 0-6 estilo
# datetime.weekday()) rompe el seed, el servicio de disponibilidad y
# el frontend de agenda.
#
# El validador `validar_rango` se ejecuta en el cliente; la BD vuelve
# a aplicar la misma regla vía ck_horarios_rango. Dos capas a propósito:
# la BD nos cubre si alguien hace un POST con curl, y Pydantic da el
# mensaje claro al frontend.
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
# Nótese que `id_secretaria` NO viene en el payload — se inyecta en el
# endpoint a partir del usuario autenticado (current_user.id). Confiar
# en lo que mande el cliente sería un agujero: cualquiera podría agendar
# en nombre de otra secretaria y desviar la auditoría.
class CitaCreate(BaseModel):
    id_paciente: int
    id_medico: int
    fecha: date
    hora: time
    motivo: Optional[str] = None


# El cambio de `estado` aquí es lo que permite cancelar/marcar como
# atendida desde PATCH /citas/{id}. Reprogramar es enviar fecha+hora
# nuevas; el endpoint valida que el nuevo slot esté libre.
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


# ============ Agenda extendida (secretaria) ============
# Estos DTOs alimentan la pantalla "Agenda del Día" de la secretaria.
# Se enriquece la cita con datos del paciente y del médico para evitar
# que el frontend tenga que hacer N requests de detalle. Es una pequeña
# violación de la pureza REST a cambio de una UI fluida en consultorios
# con red inestable.
class AgendaCitaItem(BaseModel):
    """Cita enriquecida para la pantalla de Agenda del Día de la secretaria."""
    id: int
    fecha: date
    hora: time
    # `hora_12h` viene precalculada del backend (formato '2:30 PM') para
    # no obligar al frontend a hacer la conversión 24h→12h. Pequeño detalle
    # de UX: las secretarias hablan en 12h con AM/PM, el sistema interno
    # opera en 24h.
    hora_12h: str
    estado: EstadoCita
    motivo: Optional[str] = None
    id_paciente: int
    paciente_nombre: str
    paciente_cedula: str
    id_medico: int
    medico_nombre: str
    medico_especialidad: str


# Conteos por estado: los chips de "pendientes/atendidas/canceladas"
# de la UI se pintan con estos números sin recontar en cliente.
class AgendaExtendidaResponse(BaseModel):
    total: int
    pendientes: int
    atendidas: int
    canceladas: int
    citas: list[AgendaCitaItem]


# Versión ligera para el autocomplete de "Buscar médico" — solo lo
# imprescindible para mostrar en el dropdown.
class MedicoBusquedaItem(BaseModel):
    id: int
    nombre: str
    especialidad: str


# ============ Consulta ============
# `condicion_principal` es el ÚNICO campo obligatorio — refleja la mejora
# 3.2 (diagnóstico estructurado): el médico puede dejar examen físico
# vacío en consultas rápidas, pero SIEMPRE tiene que registrar al menos
# el diagnóstico. min_length=1 evita que pase como string vacío.
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
# Cuando el admin da de alta un médico que SÍ va a usar el sistema,
# necesita crear Usuario + Médico en la misma transacción. Este DTO
# anida ambos payloads para que el endpoint pueda hacer ambos pasos
# atómicamente y rollback si alguno falla (ej. email duplicado).
#
# Si la creación se hiciera en dos llamadas separadas y el segundo fallara,
# quedaría un Usuario huérfano sin Medico vinculado — feo de limpiar.
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
# DTOs de respuesta para las pantallas de reportes del admin. NO se
# usan para entrada. La forma de cada uno está acoplada al template
# WeasyPrint correspondiente (reportes-usuarios.html, etc.) — cambiar
# un campo aquí implica revisar la plantilla HTML del PDF.
class RolStats(BaseModel):
    total: int
    activos: int
    inactivos: int


# `por_rol` es un dict anidado (rol → {total, activos, inactivos}) en
# vez de una lista de objetos porque el frontend lo consume indexado:
# por_rol["admin"], por_rol["secretaria"], etc. Más cómodo que filtrar.
class UsuariosResumen(BaseModel):
    total_usuarios: int
    por_rol: dict[str, dict[str, int]]
    fecha_generacion: datetime


# Estadísticas por médico. `tasa_atendidas` y `tasa_canceladas` son
# porcentajes 0..100 ya calculados en backend — el frontend no debería
# tener que hacer la división.
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


# ============ Especialidades (CU-17) ============
# CU-17 = gestión de catálogo de especialidades desde la UI. Antes era
# una constante hardcoded en código; ahora el admin puede agregar/editar
# desde la pantalla "Especialidades". El nombre tiene UNIQUE en BD.
#
# `activa=False` esconde la especialidad de los dropdowns pero la deja
# como referencia histórica para los médicos ya asignados con ella.
class EspecialidadCreate(BaseModel):
    nombre: str = Field(min_length=2, max_length=50)
    descripcion: Optional[str] = Field(default=None, max_length=200)


class EspecialidadUpdate(BaseModel):
    nombre: Optional[str] = Field(default=None, min_length=2, max_length=50)
    descripcion: Optional[str] = Field(default=None, max_length=200)
    activa: Optional[bool] = None


class EspecialidadRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    nombre: str
    descripcion: Optional[str] = None
    activa: bool
    fecha_creacion: datetime


# ============ Respaldos ============
# Usamos Literal en vez de los Enum de app.models porque los Literal
# integran de forma más limpia con OpenAPI (los muestra como string enum
# en el schema) y evita errores donde Pydantic intenta validar contra
# el Enum nativo y FastAPI devuelve el valor numérico/objeto. Resultado:
# el contrato HTTP es siempre el string literal.
TipoRespaldoLiteral = Literal["local", "externo", "nube"]
ProveedorNubeLiteral = Literal["s3", "gcs", "azure"]
EstadoRespaldoLiteral = Literal["en_progreso", "completado", "fallido"]


# Payload del admin para disparar un respaldo. `proveedor_nube` SOLO se
# usa cuando tipo='nube'. El endpoint valida la coherencia.
class RespaldoCreate(BaseModel):
    tipo: TipoRespaldoLiteral
    proveedor_nube: Optional[ProveedorNubeLiteral] = None


class RespaldoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    id_usuario: Optional[int]
    nombre_usuario: str
    tipo: TipoRespaldoLiteral
    proveedor_nube: Optional[ProveedorNubeLiteral] = None
    ruta_origen: str
    ruta_destino: str
    tamano_bytes: int
    hash_sha256: str
    estado: EstadoRespaldoLiteral
    mensaje_error: Optional[str] = None
    fecha_inicio: datetime
    fecha_fin: Optional[datetime] = None
    duracion_segundos: Optional[int] = None
