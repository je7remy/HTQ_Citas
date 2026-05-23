"""Modelos SQLModel del SGCM.

Esquema basado en el Anexo D de la tesis (DDL PostgreSQL).
Incluye la restricción central UNIQUE(id_medico, fecha, hora) en `citas`.

CONTEXTO: Este módulo es la verdad ÚNICA del esquema de datos del SGCM.
Cualquier campo nuevo entra primero acá y se acompaña de una migración
Alembic. Tocar la BD por fuera (init.sql, scripts sueltos) sin actualizar
estos modelos hace que SQLModel y la BD bailen distinto y rompe los tests
de integración.

OJO: el orden de las clases respeta dependencias de foreign keys
(Usuario → Paciente → Medico → Horario → Cita → Consulta → Auditoria...).
No reordenar a la ligera — Alembic lee la metadata en orden.

Convenciones del archivo:
- TIMESTAMPTZ siempre vía `_ts_column()` para mantener todo en
  America/Santo_Domingo (UTC-4, sin DST). NUNCA usar `datetime.utcnow`
  ni `default_factory=datetime.now` directos.
- Enums Python sólo viven en código de aplicación: la columna física
  es VARCHAR + CheckConstraint (ver nota en `Respaldo` más abajo).
- Campos `activo: bool` se usan para borrado lógico (soft delete) en
  vez de DELETE físico, así no se rompe el histórico ni la auditoría.
"""
from datetime import date, datetime, time
from enum import Enum
from typing import Optional

from sqlalchemy import CheckConstraint, Column, DateTime, Index, text
from sqlmodel import Field, Relationship, SQLModel

from app.core.datetime_utils import ahora_local


def _ts_column() -> Column:
    """Columna TIMESTAMPTZ NOT NULL — alineada con America/Santo_Domingo.

    CONTEXTO: usamos TIMESTAMPTZ (timezone-aware) en todas las columnas
    temporales para que PostgreSQL guarde el instante absoluto y devuelva
    la representación correcta sin importar la zona horaria del cliente.
    El valor por defecto en Python (`datetime.now()`) es naive y meterlo
    aquí silenciosamente lo trataría como UTC — por eso TODAS las columnas
    temporales usan `default_factory=ahora_local` que sí devuelve aware.
    """
    return Column(DateTime(timezone=True), nullable=False)


# ----------------------------- Enums -----------------------------
# Los enums viven en Python para tipado fuerte y autocompletado,
# pero la columna física en PostgreSQL es VARCHAR + CheckConstraint.
# Es deliberado: usar enums nativos de PostgreSQL hace que migrar
# (agregar/quitar valores) sea doloroso y se choca con `create_all()`
# cuando hay datos. VARCHAR + CHECK nos da la misma garantía con menos
# fricción operativa.


class RolUsuario(str, Enum):
    # Tres roles fijos del HTQPJB. Cambiar este enum significa también
    # tocar RBAC en app/api/deps.py (admin_required, etc.) y los seeds.
    secretaria = "secretaria"
    medico = "medico"
    admin = "admin"


class EstadoCita(str, Enum):
    # 'cancelada' es un estado terminal pero NO oculta la cita — sigue
    # apareciendo en reportes y auditoría. El índice único parcial sobre
    # citas usa `estado <> 'cancelada'` para permitir reprogramar el slot
    # liberado (ver `Cita` más abajo).
    pendiente = "pendiente"
    atendida = "atendida"
    cancelada = "cancelada"


class AccionAuditoria(str, Enum):
    # Mayúsculas a propósito: estos valores aparecen tal cual en el
    # frontend (filtros de la pantalla de auditoría) y en exports a Excel.
    # Cambiarlos rompe los reportes que ya están firmados por el HTQPJB.
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    LOGIN = "LOGIN"


class SexoPaciente(str, Enum):
    # "prefiero no decir" lleva espacio a propósito (es lo que aparece
    # en la UI y en el CHECK constraint de la tabla pacientes). El nombre
    # del miembro Python sí va con guión bajo.
    masculino = "masculino"
    femenino = "femenino"
    otro = "otro"
    prefiero_no_decir = "prefiero no decir"


class TipoRespaldo(str, Enum):
    # Tres destinos soportados por el patrón Strategy del módulo
    # app/services/backup. 'nube' requiere también un ProveedorNube.
    local = "local"
    externo = "externo"
    nube = "nube"


class ProveedorNube(str, Enum):
    # Hoy los tres están como stubs (raise NotImplementedError) — el código
    # de orquestación ya soporta el flujo, falta instalar SDK + credenciales.
    # Ver app/services/backup/nube/.
    s3 = "s3"
    gcs = "gcs"
    azure = "azure"


class EstadoRespaldo(str, Enum):
    # 'fallido' SIEMPRE deja un mensaje_error legible en la fila —
    # el admin debe poder diagnosticar sin entrar al log.
    en_progreso = "en_progreso"
    completado = "completado"
    fallido = "fallido"


# ----------------------------- Usuarios -----------------------------
# Tabla maestra de cuentas. Toda autenticación pasa por aquí, todo
# registro de auditoría apunta a aquí, y los médicos del HTQPJB se
# vinculan opcionalmente con una fila de esta tabla (id_usuario en
# Medico) para poder iniciar sesión.
#
# CUIDADO: borrar usuarios destruye la trazabilidad. El sistema usa
# `activo=False` para "dar de baja" sin perder histórico — los seeds
# incluyen un médico inactivo (Dr. Pedro Núñez) precisamente para
# verificar este flujo.
class Usuario(SQLModel, table=True):
    __tablename__ = "usuarios"
    __table_args__ = (
        # Defensa en profundidad: aunque RolUsuario tipa esto en Python,
        # la BD vuelve a validar — protege contra inserts hechos por fuera
        # (scripts, psql directo) y contra cambios en el enum que pasen
        # sin migración.
        CheckConstraint("rol IN ('secretaria','medico','admin')", name="ck_usuarios_rol"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    nombre: str = Field(max_length=100, nullable=False)
    # UNIQUE + INDEX en email: el login lo usa para SELECT en cada
    # autenticación, así que es el camino caliente. El UNIQUE evita que
    # dos cuentas compartan el mismo email aunque el front no lo valide.
    email: str = Field(max_length=100, nullable=False, unique=True, index=True)
    # bcrypt produce hashes de ~60 chars, pero dejamos margen (255) por si
    # se migra a argon2 u otra familia más larga en el futuro.
    password_hash: str = Field(max_length=255, nullable=False)
    rol: RolUsuario = Field(nullable=False)
    activo: bool = Field(default=True)
    fecha_creacion: datetime = Field(default_factory=ahora_local, sa_column=_ts_column())


# ----------------------------- Pacientes -----------------------------
# Una fila por cédula dominicana. No se borran físicamente — un paciente
# eliminado dejaría citas y consultas huérfanas que rompen los reportes
# históricos. Si se necesita "ocultar" un paciente se hace por proceso
# manual del admin, no por flujo automático.
class Paciente(SQLModel, table=True):
    __tablename__ = "pacientes"
    __table_args__ = (
        CheckConstraint(
            "sexo IN ('masculino','femenino','otro','prefiero no decir')",
            name="ck_pacientes_sexo",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    # max_length=13 para tolerar la cédula con guiones (xxx-xxxxxxx-x = 13)
    # aunque el schema PacienteBase la normaliza a 11 dígitos sin guiones.
    # El UNIQUE garantiza que un mismo paciente no se duplique aunque dos
    # secretarias lo registren en paralelo.
    cedula: str = Field(max_length=13, nullable=False, unique=True, index=True)
    nombre: str = Field(max_length=100, nullable=False)
    apellidos: str = Field(max_length=100, nullable=False)
    sexo: str = Field(max_length=20, nullable=False)
    fecha_nacimiento: date = Field(nullable=False)
    telefono: str = Field(max_length=15, nullable=False)
    direccion: Optional[str] = None
    fecha_registro: datetime = Field(default_factory=ahora_local, sa_column=_ts_column())


# ----------------------------- Médicos -----------------------------
# Un médico PUEDE no tener cuenta de usuario (id_usuario NULL): es el
# caso de médicos del HTQPJB que no usan el sistema directamente — la
# secretaria les agenda. Los que sí entran al sistema (consultorio digital,
# historial clínico) tienen su Usuario enlazado.
#
# Decisión de diseño (CU-17): `especialidad` es VARCHAR sin FK al catálogo
# `especialidades`. Se valida contra el catálogo en código (servicio),
# no en BD. Razón: minimizar blast radius sobre datos preexistentes y
# permitir renombrar el catálogo sin migración masiva de filas. Ver el
# bloque de Especialidad más abajo.
#
# Las especialidades secundarias permiten que un médico aparezca en
# múltiples filtros de búsqueda (ej. Cirugía General + Cirugía Vascular).
# Máximo 2 secundarias — basta para los casos reales del hospital.
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
# Un médico puede tener N filas de horario (típicamente 11: L-V mañana
# y tarde + sábado mañana, así arranca el seed). Cada fila es UN bloque
# atómico — si el médico parte el día (7-12 y 14-17), son DOS filas.
#
# Convención `dia_semana`: ISO weekday (1=Lunes ... 7=Domingo), igual
# que `datetime.isoweekday()`. Esa convención coincide con la tesis
# (Anexo D) y es la que asume el servicio de disponibilidad.
#
# OJO: hora_inicio < hora_fin se aplica a nivel BD — no se soporta turnos
# que cruzan la medianoche. Para el HTQPJB no hace falta porque no hay
# atención ambulatoria nocturna.
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
# Entidad central del sistema. Cada fila es una cita agendada por
# secretaria/admin para un paciente con un médico en (fecha, hora).
#
# Reglas duras de negocio (validadas en citas_service.validar_disponibilidad
# Y en BD para defensa en profundidad):
#   - No puede haber dos citas no canceladas en el mismo (médico, fecha, hora).
#   - La hora debe estar dentro de un horario activo del médico.
#   - No se agenda en el pasado.
#   - Médico debe estar activo; paciente debe existir.
#
# CONTEXTO sobre `id_secretaria`: aunque el campo se llame "secretaria",
# acepta cualquier usuario con permiso para agendar (secretaria o admin).
# El nombre es legacy de la primera iteración del modelo — renombrarlo
# implicaría migrar tests, frontend y reportes. Se quedó así.
class Cita(SQLModel, table=True):
    __tablename__ = "citas"
    __table_args__ = (
        # Índice único PARCIAL: garantiza unicidad de (medico, fecha, hora)
        # SOLO para citas no canceladas. Esto cumple a la vez:
        #  - Anexo D de la tesis: la restricción anti-duplicados sigue activa.
        #  - CU-07/CU-08 y P2.4: cancelar/reprogramar libera el horario.
        # PostgreSQL soporta esto nativamente con índice parcial (WHERE).
        #
        # CUIDADO: si esto se elimina, se podrán crear citas duplicadas
        # cuando dos secretarias agendan en paralelo y la validación de
        # disponibilidad pasa (race condition). Es nuestra última línea
        # de defensa contra el doble-booking.
        #
        # `sqlite_where` es necesario: los tests (tests/conftest.py)
        # corren contra SQLite in-memory para velocidad, y SQLite
        # también soporta índices parciales con esta sintaxis. Sin esta
        # cláusula, los tests de doble-booking no validarían igual que
        # producción.
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
    # `index=True` en id_medico y fecha: los reportes administrativos y la
    # agenda del día filtran masivamente por estos campos. Sin estos índices
    # cualquier consulta de agenda con varios miles de citas se vuelve lenta.
    id_medico: int = Field(foreign_key="medicos.id", nullable=False, index=True)
    fecha: date = Field(nullable=False, index=True)
    hora: time = Field(nullable=False)
    estado: EstadoCita = Field(default=EstadoCita.pendiente)
    motivo: Optional[str] = None
    id_secretaria: int = Field(foreign_key="usuarios.id", nullable=False)
    fecha_registro: datetime = Field(default_factory=ahora_local, sa_column=_ts_column())


# ----------------------------- Consultas -----------------------------
# Una consulta corresponde 1-a-1 con una cita atendida — el médico la
# registra al terminar la atención. El UNIQUE en `id_cita` garantiza
# que no se duplique el registro clínico aunque el médico le dé doble
# clic al botón de guardar.
#
# La consulta es lo que sustenta el historial clínico del paciente:
# cuando se borra una cita, su consulta cae por FK. Pero la cita en
# sí casi nunca se borra (se cancela) — y solo se permite registrar
# consulta sobre cita 'atendida', así que en la práctica las consultas
# son inmutables.
class Consulta(SQLModel, table=True):
    __tablename__ = "consultas"

    id: Optional[int] = Field(default=None, primary_key=True)
    id_cita: int = Field(foreign_key="citas.id", nullable=False, unique=True)
    # Diagnóstico estructurado (Mejora 3.2)
    # Migración 0005 partió el "observaciones" libre en estos 5 campos
    # estructurados. El primer campo obligatorio es `condicion_principal`
    # (diagnóstico CIE-10 o texto libre del médico). Lo demás es opcional
    # porque hay consultas rápidas que no requieren todos los apartados.
    motivo_consulta: Optional[str] = None
    examen_fisico: Optional[str] = None
    condicion_principal: str = Field(nullable=False)
    condiciones_secundarias: Optional[str] = None
    tratamiento: Optional[str] = None
    # Campo legacy: se conserva para compatibilidad con datos pre-3.2.
    # NO eliminar — hay consultas viejas (seed antiguo y datos importados)
    # que tienen información sólo aquí. Los reportes y la UI ya leen los
    # campos nuevos, pero si una fila vieja sale en historial, el front
    # muestra `observaciones` como fallback.
    observaciones: Optional[str] = None
    fecha_registro: datetime = Field(default_factory=ahora_local, sa_column=_ts_column())


# ----------------------------- Auditoría -----------------------------
# Bitácora exigida por la Ley 172-13 (Protección de Datos de R.D.) para
# operaciones críticas: alta/edición/baja de usuarios, médicos, pacientes,
# citas, consultas, respaldos y eventos de LOGIN.
#
# DECISIONES IMPORTANTES:
# - `id_usuario` es nullable + ON DELETE SET NULL (ver migración) para
#   conservar la auditoría incluso si el usuario se borra después.
# - `nombre_usuario` se denormaliza (no es JOIN) por la misma razón:
#   el reporte de auditoría tiene que mostrar QUIÉN hizo qué aunque
#   el usuario ya no exista. Esto rompe la 3FN a propósito.
# - `ip_origen` es varchar(45) — suficiente para IPv6 con prefijo
#   ("::ffff:192.168.1.1" = 21 chars; un IPv6 puro cabe en 39).
#
# CUIDADO: nunca borrar filas de esta tabla en operación normal. Si en
# algún momento crece demasiado se archiva, no se trunca.
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
# Bitácora del CU-16: cada intento de respaldo deja una fila, exitoso o
# fallido. Se almacenan TODOS los intentos (incluso los que truenan a
# medio camino) porque el admin necesita ver la causa del fallo en la
# pantalla, no en el log del contenedor.
#
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
    # Mismo patrón que en Auditoria: nombre_usuario denormalizado para
    # poder reportar "quién corrió el respaldo" aunque el usuario se borre.
    nombre_usuario: str = Field(max_length=100, nullable=False)
    tipo: str = Field(max_length=20, nullable=False)
    proveedor_nube: Optional[str] = Field(default=None, max_length=20)
    ruta_origen: str = Field(nullable=False)
    ruta_destino: str = Field(nullable=False)
    tamano_bytes: int = Field(nullable=False)
    # SHA-256 hexadecimal = 64 caracteres exactos. Lo calculamos sobre
    # el .sql generado por pg_dump y volvemos a verificar tras la entrega
    # al destino para detectar corrupción en tránsito (USB defectuoso,
    # transferencia interrumpida, etc.).
    hash_sha256: str = Field(max_length=64, nullable=False)
    estado: str = Field(max_length=20, nullable=False)
    mensaje_error: Optional[str] = None
    fecha_inicio: datetime = Field(default_factory=ahora_local, sa_column=_ts_column())
    # fecha_fin se llena al cerrar el flujo (éxito o fallo). NULL solo
    # tendría sentido si el proceso quedó colgado — en la práctica no
    # debería existir, pero se permite para no romper el insert inicial.
    fecha_fin: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    duracion_segundos: Optional[int] = None
