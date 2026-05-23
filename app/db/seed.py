"""Sistema de seeders del SGCM.

Pobla la base de datos con datos realistas del HTQPJB para que el sistema sea
usable desde el primer arranque, sin necesidad de registro manual. Todas las
funciones son idempotentes: verifican con SELECT antes de INSERT, de modo que
ejecutar el seed dos veces no duplica datos.

Generan además registros de auditoría coherentes con cada operación,
respetando el modelo de auditoría transaccional exigido por la Ley 172-13.
"""
from __future__ import annotations

import logging
import random
from datetime import date, datetime, time, timedelta
from typing import Iterable, Optional

from sqlmodel import Session, select

from app.core.datetime_utils import ahora_local
from app.core.security import hash_password
from app.models import (
    AccionAuditoria,
    Auditoria,
    Cita,
    Consulta,
    EstadoCita,
    Horario,
    Medico,
    Paciente,
    RolUsuario,
    SexoPaciente,
    Usuario,
)

logger = logging.getLogger(__name__)

# Semilla determinista — el seed reproducible facilita el debugging y la idempotencia.
_SEED = 20260515

# Credenciales públicas (también documentadas en README.md).
ADMIN_EMAIL = "admin@htqpjb.gob.do"
ADMIN_PASSWORD = "Admin123!"
SECRETARIA_PASSWORD = "Secretaria123!"
MEDICO_PASSWORD = "Medico123!"


# ====================================================================
# Faker (opcional, con localización es_ES). El módulo no rompe si no está.
# ====================================================================
try:  # pragma: no cover — disponibilidad de la lib
    from faker import Faker  # type: ignore

    _faker: Optional["Faker"] = Faker("es_ES")
    _faker.seed_instance(_SEED)
except Exception:  # pragma: no cover — fallback sin Faker
    _faker = None


# ====================================================================
# Cédula dominicana — algoritmo de verificación REAL (no aleatorio).
# ====================================================================
def _digito_verificador_cedula(primeros_diez: str) -> int:
    """Calcula el dígito verificador de una cédula dominicana (módulo 10,
    pesos alternados 1-2 sobre los primeros 10 dígitos).
    """
    pesos = (1, 2) * 5
    suma = 0
    for ch, p in zip(primeros_diez, pesos):
        prod = int(ch) * p
        if prod >= 10:
            prod -= 9
        suma += prod
    return (10 - (suma % 10)) % 10


def cedula_dominicana_es_valida(cedula: str) -> bool:
    """True si la cédula tiene 11 dígitos y su dígito verificador es correcto."""
    cedula = cedula.replace("-", "").strip()
    if len(cedula) != 11 or not cedula.isdigit():
        return False
    return _digito_verificador_cedula(cedula[:10]) == int(cedula[10])


def generar_cedula_dominicana(rng: random.Random) -> str:
    """Genera una cédula con dígito verificador correcto.

    El primer bloque (001–090) representa el código municipal; usamos un rango
    conservador que cubre municipios reales de R.D.
    """
    municipio = f"{rng.randint(1, 90):03d}"
    serie = f"{rng.randint(0, 9999999):07d}"
    primeros_diez = municipio + serie
    return primeros_diez + str(_digito_verificador_cedula(primeros_diez))


# ====================================================================
# Catálogos auxiliares de nombres dominicanos (fallback si Faker no rinde).
# ====================================================================
_NOMBRES_M = [
    "Juan", "Pedro", "Luis", "Carlos", "Miguel", "José", "Ramón", "Francisco",
    "Antonio", "Manuel", "Rafael", "Eduardo", "Andrés", "Domingo", "Felipe",
    "Héctor", "Julio", "Daniel", "Jorge", "Víctor",
]
_NOMBRES_F = [
    "María", "Ana", "Rosa", "Juana", "Elena", "Patricia", "Carmen", "Mercedes",
    "Altagracia", "Yolanda", "Sandra", "Lucía", "Marta", "Teresa", "Isabel",
    "Cristina", "Yokasta", "Damaris", "Esperanza", "Francisca",
]
_APELLIDOS_RD = [
    "Pérez", "Rodríguez", "Martínez", "Santos", "García", "Fernández", "López",
    "Jiménez", "Hernández", "Sánchez", "Reyes", "Castillo", "Peña", "Cabrera",
    "Mejía", "Ramírez", "Rosario", "Núñez", "Polanco", "De los Santos",
    "Tejada", "Almonte", "Espinal", "Liriano", "Vásquez",
]
_CALLES_RD = [
    "Calle Duarte", "Avenida Mella", "Calle Sánchez", "Avenida 27 de Febrero",
    "Calle Hostos", "Avenida Independencia", "Calle Padre Billini",
    "Calle Pedro Henríquez Ureña", "Avenida Gregorio Luperón",
    "Calle El Sol", "Calle Las Carreras",
]
_SECTORES_LV = [
    "La Vega centro", "Don Bosco", "Villa Rosa", "Pueblo Nuevo", "Los Cacicazgos",
    "Las Carolinas", "Los Pomos", "El Carmen",
]


def _nombre_aleatorio(rng: random.Random, sexo: str) -> tuple[str, str]:
    if sexo == "masculino":
        nombre = rng.choice(_NOMBRES_M)
    elif sexo == "femenino":
        nombre = rng.choice(_NOMBRES_F)
    else:
        nombre = rng.choice(_NOMBRES_M + _NOMBRES_F)
    apellidos = f"{rng.choice(_APELLIDOS_RD)} {rng.choice(_APELLIDOS_RD)}"
    return nombre, apellidos


def _telefono_rd(rng: random.Random) -> str:
    """Formato 809/829/849-XXX-XXXX."""
    prefijo = rng.choice(["809", "829", "849"])
    a = rng.randint(200, 999)
    b = rng.randint(1000, 9999)
    return f"{prefijo}-{a}-{b}"


def _direccion_rd(rng: random.Random) -> str:
    numero = rng.randint(1, 250)
    return f"{rng.choice(_CALLES_RD)} #{numero}, {rng.choice(_SECTORES_LV)}, La Vega"


# ====================================================================
# Plantillas clínicas por especialidad (para seed_consultas).
# ====================================================================
_PLANTILLAS_POR_ESPECIALIDAD: dict[str, list[dict]] = {
    "Ortopedia y Traumatología": [
        {
            "motivo_consulta": "Dolor de rodilla derecha al subir escaleras",
            "examen_fisico": "Limitación de movimiento, no edema, sin signos de inestabilidad",
            "condicion_principal": "M25.561 Dolor en rodilla derecha",
            "tratamiento": "Ibuprofeno 400 mg cada 8 horas, reposo relativo, control en 15 días",
        },
        {
            "motivo_consulta": "Esguince de tobillo izquierdo tras caída",
            "examen_fisico": "Edema moderado, dolor a la palpación lateral, rango limitado",
            "condicion_principal": "S93.4 Esguince de tobillo izquierdo",
            "tratamiento": "Inmovilización con férula 10 días, hielo local, AINEs",
        },
    ],
    "Cirugía General": [
        {
            "motivo_consulta": "Dolor abdominal en fosa ilíaca derecha de 24 horas",
            "examen_fisico": "Blumberg positivo, defensa muscular leve",
            "condicion_principal": "K35.80 Apendicitis aguda, no especificada",
            "tratamiento": "Ingreso para apendicectomía, antibioticoterapia preoperatoria",
        },
    ],
    "Cirugía Vascular": [
        {
            "motivo_consulta": "Várices dolorosas en miembro inferior derecho",
            "examen_fisico": "Várices tronculares visibles, sin signos de trombosis",
            "condicion_principal": "I83.90 Várices de miembros inferiores",
            "tratamiento": "Medias compresivas, evaluación para escleroterapia",
        },
    ],
    "Cirugía Torácica": [
        {
            "motivo_consulta": "Dolor torácico persistente con disnea leve",
            "examen_fisico": "Ruidos respiratorios disminuidos en base izquierda",
            "condicion_principal": "J93.0 Neumotórax espontáneo",
            "tratamiento": "Radiografía de tórax control, evaluación para drenaje pleural",
        },
    ],
    "Cirugía Plástica": [
        {
            "motivo_consulta": "Cicatriz hipertrófica en antebrazo post-quemadura",
            "examen_fisico": "Cicatriz elevada, eritematosa, sin signos de infección",
            "condicion_principal": "L91.0 Cicatriz hipertrófica",
            "tratamiento": "Láminas de silicona, control en 30 días",
        },
    ],
    "Cirugía Pediátrica": [
        {
            "motivo_consulta": "Tumoración inguinal derecha en niño de 4 años",
            "examen_fisico": "Hernia inguinal reductible, sin signos de incarceración",
            "condicion_principal": "K40.90 Hernia inguinal unilateral",
            "tratamiento": "Programar herniorrafia electiva, vigilancia familiar",
        },
    ],
    "Cirugía Ginecológica": [
        {
            "motivo_consulta": "Sangrado uterino anormal de 3 meses de evolución",
            "examen_fisico": "Útero aumentado de tamaño, móvil, no doloroso",
            "condicion_principal": "D25.9 Leiomioma del útero, no especificado",
            "tratamiento": "Solicitar sonografía pélvica, control en 21 días",
        },
    ],
    "Neurocirugía": [
        {
            "motivo_consulta": "Cefalea progresiva con vómitos matutinos",
            "examen_fisico": "Fondo de ojo: edema de papila incipiente",
            "condicion_principal": "G93.2 Hipertensión intracraneal benigna",
            "tratamiento": "TAC craneal urgente, acetazolamida 250 mg cada 12 horas",
        },
    ],
    "Cirugía Maxilofacial": [
        {
            "motivo_consulta": "Trauma facial por accidente de tránsito",
            "examen_fisico": "Crepitación malar derecha, equimosis periorbitaria",
            "condicion_principal": "S02.40 Fractura malar y maxilar",
            "tratamiento": "TAC facial, dieta blanda, evaluación para osteosíntesis",
        },
    ],
    "Anestesiología": [
        {
            "motivo_consulta": "Evaluación preanestésica para colecistectomía electiva",
            "examen_fisico": "Vía aérea Mallampati II, ASA II",
            "condicion_principal": "Z01.818 Evaluación preoperatoria",
            "tratamiento": "Apto para anestesia general, ayuno 8 horas previas",
        },
    ],
    "Medicina Interna": [
        {
            "motivo_consulta": "Cifras tensionales elevadas en chequeo de rutina",
            "examen_fisico": "TA 160/95, FC 82, sin soplos cardiacos",
            "condicion_principal": "I10 Hipertensión esencial",
            "tratamiento": "Enalapril 10 mg cada 24 horas, dieta hiposódica, control en 30 días",
        },
        {
            "motivo_consulta": "Poliuria y polidipsia de 2 semanas",
            "examen_fisico": "Mucosas semihúmedas, IMC 31",
            "condicion_principal": "E11.9 Diabetes mellitus tipo 2 sin complicaciones",
            "tratamiento": "Metformina 850 mg cada 12 horas, HbA1c y perfil lipídico",
        },
    ],
    "Urología": [
        {
            "motivo_consulta": "Disuria y polaquiuria de 3 días",
            "examen_fisico": "Puño percusión renal negativa, sin globo vesical",
            "condicion_principal": "N39.0 Infección de vías urinarias",
            "tratamiento": "Ciprofloxacina 500 mg cada 12 horas por 7 días",
        },
    ],
    "Oftalmología": [
        {
            "motivo_consulta": "Visión borrosa progresiva de cerca",
            "examen_fisico": "Agudeza visual J5, fondo de ojo normal",
            "condicion_principal": "H52.4 Presbicia",
            "tratamiento": "Corrección óptica con lentes para lectura +1.50",
        },
    ],
    "Otorrinolaringología": [
        {
            "motivo_consulta": "Otalgia derecha tras baño en piscina",
            "examen_fisico": "Conducto auditivo eritematoso, tímpano íntegro",
            "condicion_principal": "H60.391 Otitis externa, oído derecho",
            "tratamiento": "Ciprofloxacina ótica 3 gotas cada 8 horas por 7 días",
        },
    ],
    "Medicina Física y Rehabilitación": [
        {
            "motivo_consulta": "Lumbalgia crónica de 2 meses",
            "examen_fisico": "Contractura paravertebral L4-L5, Lasègue negativo",
            "condicion_principal": "M54.5 Lumbago no especificado",
            "tratamiento": "10 sesiones de fisioterapia, ejercicios de Williams",
        },
    ],
    "Radiología y Diagnóstico por Imágenes": [
        {
            "motivo_consulta": "Estudio sonográfico abdominal por dolor recurrente",
            "examen_fisico": "Abdomen blando, doloroso a la palpación profunda",
            "condicion_principal": "R10.9 Dolor abdominal no especificado",
            "tratamiento": "Sonografía abdominal completa, control con resultados",
        },
    ],
    "Laboratorio Clínico": [
        {
            "motivo_consulta": "Solicitud de perfil de control anual",
            "examen_fisico": "Paciente asintomático",
            "condicion_principal": "Z00.00 Examen médico general sin anormalidades",
            "tratamiento": "Hemograma, glicemia, perfil lipídico, perfil renal",
        },
    ],
    "Emergenciología": [
        {
            "motivo_consulta": "Fiebre y malestar general de 24 horas",
            "examen_fisico": "T° 38.7, faringe eritematosa, no exudado",
            "condicion_principal": "J06.9 Infección aguda de vías respiratorias superiores",
            "tratamiento": "Acetaminofén 500 mg cada 6 horas, abundante líquido",
        },
    ],
}

_PLANTILLA_GENERICA = {
    "motivo_consulta": "Control médico de rutina",
    "examen_fisico": "Paciente en buen estado general, signos vitales estables",
    "condicion_principal": "Z00.00 Examen médico general sin hallazgos relevantes",
    "tratamiento": "Continuar con régimen habitual, control en 6 meses",
}


_MOTIVOS_CITA_GENERICOS = [
    "Consulta de seguimiento",
    "Primera consulta",
    "Control post-operatorio",
    "Evaluación por especialista",
    "Revisión de exámenes",
    "Renovación de tratamiento",
]


# ====================================================================
# Helper de auditoría — añade un registro a la sesión SIN commit.
# ====================================================================
def _audit(
    session: Session,
    actor: Optional[Usuario],
    accion: AccionAuditoria,
    tabla: str,
    id_registro: Optional[int],
    detalle: str,
) -> None:
    log = Auditoria(
        id_usuario=actor.id if actor else None,
        nombre_usuario=actor.nombre if actor else "[seed]",
        accion=accion,
        tabla_afectada=tabla,
        id_registro=id_registro,
        detalle=detalle,
        ip_origen="127.0.0.1",
        fecha_hora=ahora_local(),
    )
    session.add(log)


# ====================================================================
# Configuración declarativa de usuarios.
# ====================================================================
_USUARIOS_BASE: list[dict] = [
    # Administrador
    {
        "email": ADMIN_EMAIL,
        "nombre": "Administrador SGCM",
        "password": ADMIN_PASSWORD,
        "rol": RolUsuario.admin,
        "activo": True,
    },
    # Secretarias (4)
    {
        "email": "secretaria.maria@htqpjb.gob.do",
        "nombre": "María Fernández",
        "password": SECRETARIA_PASSWORD,
        "rol": RolUsuario.secretaria,
        "activo": True,
    },
    {
        "email": "secretaria.juana@htqpjb.gob.do",
        "nombre": "Juana Rodríguez",
        "password": SECRETARIA_PASSWORD,
        "rol": RolUsuario.secretaria,
        "activo": True,
    },
    {
        "email": "secretaria.elena@htqpjb.gob.do",
        "nombre": "Elena Martínez",
        "password": SECRETARIA_PASSWORD,
        "rol": RolUsuario.secretaria,
        "activo": True,
    },
    {
        "email": "secretaria.rosa@htqpjb.gob.do",
        "nombre": "Rosa Peña",
        "password": SECRETARIA_PASSWORD,
        "rol": RolUsuario.secretaria,
        "activo": True,
    },
    # Médicos (5 activos + 1 inactivo)
    {
        "email": "dr.jperez@htqpjb.gob.do",
        "nombre": "Dr. Juan Pérez",
        "password": MEDICO_PASSWORD,
        "rol": RolUsuario.medico,
        "activo": True,
        "_especialidad": "Ortopedia y Traumatología",
        "_secundarias": (),
        "_telefono": "809-555-0101",
    },
    {
        "email": "dra.aramirez@htqpjb.gob.do",
        "nombre": "Dra. Ana Ramírez",
        "password": MEDICO_PASSWORD,
        "rol": RolUsuario.medico,
        "activo": True,
        "_especialidad": "Medicina Interna",
        "_secundarias": ("Emergenciología",),
        "_telefono": "809-555-0102",
    },
    {
        "email": "dr.cgarcia@htqpjb.gob.do",
        "nombre": "Dr. Carlos García",
        "password": MEDICO_PASSWORD,
        "rol": RolUsuario.medico,
        "activo": True,
        "_especialidad": "Cirugía General",
        "_secundarias": ("Cirugía Vascular", "Cirugía Torácica"),
        "_telefono": "809-555-0103",
    },
    {
        "email": "dra.lcastillo@htqpjb.gob.do",
        "nombre": "Dra. Lucía Castillo",
        "password": MEDICO_PASSWORD,
        "rol": RolUsuario.medico,
        "activo": True,
        "_especialidad": "Oftalmología",
        "_secundarias": (),
        "_telefono": "809-555-0104",
    },
    {
        "email": "dr.rsantos@htqpjb.gob.do",
        "nombre": "Dr. Ramón Santos",
        "password": MEDICO_PASSWORD,
        "rol": RolUsuario.medico,
        "activo": True,
        "_especialidad": "Neurocirugía",
        "_secundarias": ("Cirugía Maxilofacial",),
        "_telefono": "809-555-0105",
    },
    {
        "email": "dr.inactivo@htqpjb.gob.do",
        "nombre": "Dr. Pedro Núñez",
        "password": MEDICO_PASSWORD,
        "rol": RolUsuario.medico,
        "activo": False,  # Usuario inactivo — para probar el flag
        "_especialidad": "Urología",
        "_secundarias": (),
        "_telefono": "809-555-0106",
    },
]


# ====================================================================
# Médicos extra (sin usuario vinculado) — cubren más especialidades.
# ====================================================================
_MEDICOS_SIN_USUARIO: list[dict] = [
    {
        "nombre": "Dr. Miguel Hernández",
        "especialidad": "Otorrinolaringología",
        "_secundarias": ("Emergenciología",),
        "telefono": "809-555-0201",
        "activo": True,
    },
    {
        "nombre": "Dra. Patricia Mejía",
        "especialidad": "Medicina Física y Rehabilitación",
        "_secundarias": (),
        "telefono": "809-555-0202",
        "activo": True,
    },
    {
        "nombre": "Dr. Héctor Tejada",
        "especialidad": "Cirugía Pediátrica",
        "_secundarias": ("Cirugía Plástica",),
        "telefono": "809-555-0203",
        "activo": True,
    },
    {
        "nombre": "Dra. Yolanda Reyes",
        "especialidad": "Anestesiología",
        "_secundarias": (),
        "telefono": "809-555-0204",
        "activo": False,  # Médico inactivo (sin usuario)
    },
]


# ====================================================================
# seed_usuarios
# ====================================================================
def seed_usuarios(session: Session) -> dict[str, Usuario]:
    """Crea el conjunto base de usuarios. Devuelve mapa email -> Usuario.

    Idempotente: cada usuario se busca por email antes de crearse.
    """
    creados: dict[str, Usuario] = {}
    nuevos: list[Usuario] = []

    for cfg in _USUARIOS_BASE:
        existing = session.exec(
            select(Usuario).where(Usuario.email == cfg["email"])
        ).first()
        if existing:
            creados[cfg["email"]] = existing
            continue
        u = Usuario(
            nombre=cfg["nombre"],
            email=cfg["email"],
            password_hash=hash_password(cfg["password"]),
            rol=cfg["rol"],
            activo=cfg["activo"],
        )
        session.add(u)
        nuevos.append(u)
        creados[cfg["email"]] = u

    session.flush()

    # Auditoría — usamos el admin como actor del seed.
    admin = creados.get(ADMIN_EMAIL)
    for u in nuevos:
        _audit(
            session,
            admin,
            AccionAuditoria.CREATE,
            "usuarios",
            u.id,
            f"Seed alta usuario rol={u.rol.value} email={u.email}",
        )

    session.commit()
    logger.info("seed_usuarios: %d nuevo(s), %d total(es)", len(nuevos), len(creados))
    return creados


# ====================================================================
# seed_medicos
# ====================================================================
def seed_medicos(
    session: Session, usuarios: Optional[dict[str, Usuario]] = None
) -> list[Medico]:
    """Crea médicos vinculados a los usuarios médicos y extra sin usuario.

    Devuelve la lista completa de médicos (existentes + nuevos).
    Idempotente: por usuario vinculado o por (nombre, especialidad).
    """
    if usuarios is None:
        usuarios = {u.email: u for u in session.exec(select(Usuario)).all()}

    admin = usuarios.get(ADMIN_EMAIL)
    nuevos: list[Medico] = []

    # 1) Médicos vinculados a usuarios médicos
    for cfg in _USUARIOS_BASE:
        if cfg["rol"] != RolUsuario.medico:
            continue
        usuario = usuarios.get(cfg["email"])
        if not usuario:
            continue
        existing = session.exec(
            select(Medico).where(Medico.id_usuario == usuario.id)
        ).first()
        if existing:
            continue
        secundarias = list(cfg["_secundarias"])
        m = Medico(
            id_usuario=usuario.id,
            nombre=cfg["nombre"].removeprefix("Dr. ").removeprefix("Dra. "),
            especialidad=cfg["_especialidad"],
            especialidad_secundaria_1=secundarias[0] if len(secundarias) >= 1 else None,
            especialidad_secundaria_2=secundarias[1] if len(secundarias) >= 2 else None,
            telefono=cfg["_telefono"],
            activo=cfg["activo"],  # respeta el flag del usuario
        )
        session.add(m)
        nuevos.append(m)

    # 2) Médicos extra sin usuario vinculado
    for cfg in _MEDICOS_SIN_USUARIO:
        nombre_normalizado = cfg["nombre"].removeprefix("Dr. ").removeprefix("Dra. ")
        existing = session.exec(
            select(Medico).where(
                Medico.nombre == nombre_normalizado,
                Medico.especialidad == cfg["especialidad"],
            )
        ).first()
        if existing:
            continue
        secundarias = list(cfg["_secundarias"])
        m = Medico(
            id_usuario=None,
            nombre=nombre_normalizado,
            especialidad=cfg["especialidad"],
            especialidad_secundaria_1=secundarias[0] if len(secundarias) >= 1 else None,
            especialidad_secundaria_2=secundarias[1] if len(secundarias) >= 2 else None,
            telefono=cfg["telefono"],
            activo=cfg["activo"],
        )
        session.add(m)
        nuevos.append(m)

    session.flush()

    for m in nuevos:
        _audit(
            session,
            admin,
            AccionAuditoria.CREATE,
            "medicos",
            m.id,
            f"Seed alta médico {m.nombre} ({m.especialidad})",
        )

    session.commit()
    todos = session.exec(select(Medico)).all()
    logger.info("seed_medicos: %d nuevo(s), %d total(es)", len(nuevos), len(todos))
    return list(todos)


# ====================================================================
# seed_horarios
# ====================================================================
# L-V mañana 7:00-12:00, tarde 14:00-17:00; Sábado mañana 8:00-12:00.
_HORARIOS_BASE: tuple[tuple[int, time, time], ...] = (
    (1, time(7, 0), time(12, 0)), (1, time(14, 0), time(17, 0)),  # Lunes
    (2, time(7, 0), time(12, 0)), (2, time(14, 0), time(17, 0)),  # Martes
    (3, time(7, 0), time(12, 0)), (3, time(14, 0), time(17, 0)),  # Miércoles
    (4, time(7, 0), time(12, 0)), (4, time(14, 0), time(17, 0)),  # Jueves
    (5, time(7, 0), time(12, 0)), (5, time(14, 0), time(17, 0)),  # Viernes
    (6, time(8, 0), time(12, 0)),                                  # Sábado
    # Domingo: sin atención
)


def seed_horarios(
    session: Session, medicos: Optional[Iterable[Medico]] = None
) -> int:
    """Configura horarios estándar para cada médico ACTIVO.

    Idempotente: solo crea horarios si el médico aún no tiene ninguno.
    Devuelve el número de horarios nuevos creados.
    """
    if medicos is None:
        medicos = session.exec(select(Medico).where(Medico.activo == True)).all()  # noqa: E712

    admin = session.exec(
        select(Usuario).where(Usuario.email == ADMIN_EMAIL)
    ).first()

    creados = 0
    for m in medicos:
        if not m.activo:
            continue
        ya_tiene = session.exec(
            select(Horario).where(Horario.id_medico == m.id)
        ).first()
        if ya_tiene:
            continue
        for dia, hi, hf in _HORARIOS_BASE:
            session.add(
                Horario(
                    id_medico=m.id,
                    dia_semana=dia,
                    hora_inicio=hi,
                    hora_fin=hf,
                    activo=True,
                )
            )
            creados += 1
        session.flush()
        _audit(
            session,
            admin,
            AccionAuditoria.CREATE,
            "horarios",
            m.id,
            f"Seed horarios estándar para médico {m.nombre}",
        )

    session.commit()
    logger.info("seed_horarios: %d horarios creados", creados)
    return creados


# ====================================================================
# seed_pacientes
# ====================================================================
_OBJETIVO_PACIENTES = 40


def seed_pacientes(session: Session) -> list[Paciente]:
    """Crea ~40 pacientes con cédulas dominicanas válidas.

    Idempotente: si ya hay pacientes registrados, devuelve los existentes
    sin crear nuevos.
    """
    existentes = session.exec(select(Paciente)).all()
    if existentes:
        logger.info("seed_pacientes: %d ya existen, omito", len(existentes))
        return list(existentes)

    rng = random.Random(_SEED + 100)
    admin = session.exec(
        select(Usuario).where(Usuario.email == ADMIN_EMAIL)
    ).first()
    sexos = list(SexoPaciente)
    hoy = date.today()

    creados: list[Paciente] = []
    intentos = 0
    while len(creados) < _OBJETIVO_PACIENTES and intentos < _OBJETIVO_PACIENTES * 5:
        intentos += 1
        cedula = generar_cedula_dominicana(rng)
        # Defensa: si tropezamos con una cédula ya emitida (improbable), reintentar.
        if session.exec(
            select(Paciente).where(Paciente.cedula == cedula)
        ).first():
            continue

        sexo = rng.choice(sexos).value
        nombre, apellidos = _nombre_aleatorio(rng, sexo)
        edad_anos = rng.randint(5, 85)
        # Aproximación: misma fecha del año, edad años atrás.
        fecha_nac = hoy.replace(year=hoy.year - edad_anos) - timedelta(
            days=rng.randint(0, 364)
        )
        direccion = _direccion_rd(rng) if rng.random() < 0.6 else None

        p = Paciente(
            cedula=cedula,
            nombre=nombre,
            apellidos=apellidos,
            sexo=sexo,
            fecha_nacimiento=fecha_nac,
            telefono=_telefono_rd(rng),
            direccion=direccion,
        )
        session.add(p)
        creados.append(p)

    session.flush()

    for p in creados:
        _audit(
            session,
            admin,
            AccionAuditoria.CREATE,
            "pacientes",
            p.id,
            f"Seed alta paciente cedula={p.cedula}",
        )

    session.commit()
    logger.info("seed_pacientes: %d creados", len(creados))
    return creados


# ====================================================================
# seed_citas
# ====================================================================
_OBJETIVO_CITAS = 50


def _slots_para(
    session: Session, medico: Medico, fecha_obj: date
) -> list[time]:
    """Genera los slots de 30 minutos disponibles para un médico en una fecha."""
    dia_semana = fecha_obj.isoweekday()
    bloques = session.exec(
        select(Horario).where(
            Horario.id_medico == medico.id,
            Horario.activo == True,  # noqa: E712
            Horario.dia_semana == dia_semana,
        )
    ).all()
    slots: list[time] = []
    for b in bloques:
        cur = datetime.combine(fecha_obj, b.hora_inicio)
        fin = datetime.combine(fecha_obj, b.hora_fin)
        while cur < fin:
            slots.append(cur.time())
            cur += timedelta(minutes=30)
    return slots


def seed_citas(
    session: Session,
    medicos: Optional[Iterable[Medico]] = None,
    pacientes: Optional[Iterable[Paciente]] = None,
    secretarias: Optional[Iterable[Usuario]] = None,
) -> list[Cita]:
    """Crea ~50 citas distribuidas por estado y fecha.

    Distribución:
      - 30% pendientes futuras (5-30 días)
      - 30% atendidas pasadas (1-60 días)
      - 10% canceladas (mix pasado/futuro)
      - 30% pendientes para hoy y los próximos 3 días

    Idempotente: si ya hay citas, no crea nuevas.
    """
    existentes = session.exec(select(Cita)).all()
    if existentes:
        logger.info("seed_citas: %d ya existen, omito", len(existentes))
        return list(existentes)

    if medicos is None:
        medicos = session.exec(select(Medico)).all()
    if pacientes is None:
        pacientes = session.exec(select(Paciente)).all()
    if secretarias is None:
        secretarias = session.exec(
            select(Usuario).where(Usuario.rol == RolUsuario.secretaria)
        ).all()

    activos = [m for m in medicos if m.activo]
    pacientes = list(pacientes)
    secretarias = list(secretarias)
    if not activos or not pacientes or not secretarias:
        logger.warning("seed_citas: faltan médicos activos / pacientes / secretarias")
        return []

    rng = random.Random(_SEED + 200)
    ahora = ahora_local()
    hoy = ahora.date()
    hora_actual = ahora.time()

    creadas: list[Cita] = []
    ocupados: set[tuple[int, date, time]] = set()

    def crear(
        estado: EstadoCita, fecha_factory, intentos: int = 60
    ) -> Optional[Cita]:
        """Intenta crear una cita. fecha_factory devuelve una fecha candidata por intento
        — así descartamos los domingos (sin horarios) sin perder cuota de la distribución.
        """
        for _ in range(intentos):
            fecha_obj = fecha_factory()
            m = rng.choice(activos)
            slots = _slots_para(session, m, fecha_obj)
            if fecha_obj == hoy:
                slots = [s for s in slots if s > hora_actual]
            if not slots:
                continue
            hora = rng.choice(slots)
            key = (m.id, fecha_obj, hora)
            # El índice único es PARCIAL — solo aplica si estado != cancelada.
            if estado != EstadoCita.cancelada and key in ocupados:
                continue
            paciente = rng.choice(pacientes)
            sec = rng.choice(secretarias)
            cita = Cita(
                id_paciente=paciente.id,
                id_medico=m.id,
                fecha=fecha_obj,
                hora=hora,
                estado=estado,
                motivo=rng.choice(_MOTIVOS_CITA_GENERICOS),
                id_secretaria=sec.id,
            )
            session.add(cita)
            session.flush()
            if estado != EstadoCita.cancelada:
                ocupados.add(key)
            return cita
        return None

    n_pendientes_futuras = int(_OBJETIVO_CITAS * 0.30)
    n_atendidas = int(_OBJETIVO_CITAS * 0.30)
    n_canceladas = int(_OBJETIVO_CITAS * 0.10)
    n_proximos_dias = _OBJETIVO_CITAS - (n_pendientes_futuras + n_atendidas + n_canceladas)

    # 30% pendientes futuras (5-30 días)
    for _ in range(n_pendientes_futuras):
        c = crear(
            EstadoCita.pendiente,
            lambda: hoy + timedelta(days=rng.randint(5, 30)),
        )
        if c:
            creadas.append(c)

    # 30% atendidas pasadas (1-60 días)
    for _ in range(n_atendidas):
        c = crear(
            EstadoCita.atendida,
            lambda: hoy - timedelta(days=rng.randint(1, 60)),
        )
        if c:
            creadas.append(c)

    # 10% canceladas (mix pasado/futuro)
    for _ in range(n_canceladas):
        c = crear(
            EstadoCita.cancelada,
            lambda: hoy + timedelta(days=rng.choice([-1, 1]) * rng.randint(1, 30)),
        )
        if c:
            creadas.append(c)

    # 30% próximos días (hoy + 3)
    for _ in range(n_proximos_dias):
        c = crear(
            EstadoCita.pendiente,
            lambda: hoy + timedelta(days=rng.randint(0, 3)),
        )
        if c:
            creadas.append(c)

    # Auditoría — la secretaria de la cita es el actor natural.
    sec_actor_por_id = {s.id: s for s in secretarias}
    for c in creadas:
        actor = sec_actor_por_id.get(c.id_secretaria, secretarias[0])
        _audit(
            session,
            actor,
            AccionAuditoria.CREATE,
            "citas",
            c.id,
            f"Seed cita {c.estado.value} fecha={c.fecha.isoformat()} hora={c.hora.isoformat()}",
        )

    session.commit()
    logger.info("seed_citas: %d creadas", len(creadas))
    return creadas


# ====================================================================
# seed_consultas
# ====================================================================
def seed_consultas(
    session: Session, citas: Optional[Iterable[Cita]] = None
) -> list[Consulta]:
    """Por cada cita atendida sin consulta, crea una consulta plausible."""
    existentes = session.exec(select(Consulta)).all()
    if existentes:
        logger.info("seed_consultas: %d ya existen, omito", len(existentes))
        return list(existentes)

    if citas is None:
        citas = session.exec(
            select(Cita).where(Cita.estado == EstadoCita.atendida)
        ).all()
    atendidas = [c for c in citas if c.estado == EstadoCita.atendida]
    if not atendidas:
        logger.info("seed_consultas: no hay citas atendidas")
        return []

    rng = random.Random(_SEED + 300)
    creadas: list[Consulta] = []
    medicos_cache: dict[int, Medico] = {}

    for cita in atendidas:
        if cita.id_medico not in medicos_cache:
            m = session.get(Medico, cita.id_medico)
            if m:
                medicos_cache[cita.id_medico] = m
        medico = medicos_cache.get(cita.id_medico)
        especialidad = medico.especialidad if medico else None

        plantillas = _PLANTILLAS_POR_ESPECIALIDAD.get(especialidad or "", [])
        plantilla = rng.choice(plantillas) if plantillas else _PLANTILLA_GENERICA

        consulta = Consulta(
            id_cita=cita.id,
            motivo_consulta=plantilla["motivo_consulta"],
            examen_fisico=plantilla["examen_fisico"],
            condicion_principal=plantilla["condicion_principal"],
            condiciones_secundarias=plantilla.get("condiciones_secundarias"),
            tratamiento=plantilla["tratamiento"],
        )
        session.add(consulta)
        creadas.append(consulta)

    session.flush()

    # Auditoría — el médico de la cita es el actor que registra la consulta.
    usuarios_por_medico = {
        m.id: session.exec(
            select(Usuario).where(Usuario.id == m.id_usuario)
        ).first()
        for m in medicos_cache.values()
        if m.id_usuario
    }
    for c in creadas:
        cita = next(x for x in atendidas if x.id == c.id_cita)
        medico = medicos_cache.get(cita.id_medico)
        actor = usuarios_por_medico.get(medico.id) if medico else None
        _audit(
            session,
            actor,
            AccionAuditoria.CREATE,
            "consultas",
            c.id,
            f"Seed consulta para cita {c.id_cita}",
        )

    session.commit()
    logger.info("seed_consultas: %d creadas", len(creadas))
    return creadas


# ====================================================================
# Orquestador
# ====================================================================
def seed_all(session: Session) -> dict:
    """Ejecuta todos los seeders en orden. Devuelve resumen."""
    usuarios = seed_usuarios(session)
    medicos = seed_medicos(session, usuarios)
    seed_horarios(session, medicos)
    pacientes = seed_pacientes(session)
    secretarias = [u for u in usuarios.values() if u.rol == RolUsuario.secretaria]
    citas = seed_citas(session, medicos, pacientes, secretarias)
    consultas = seed_consultas(session, citas)
    return {
        "usuarios": len(usuarios),
        "medicos": len(medicos),
        "pacientes": len(pacientes),
        "citas": len(citas),
        "consultas": len(consultas),
    }


# ====================================================================
# Reset (cuidado: destructivo). Usado por la CLI con --reset.
# ====================================================================
def reset_datos(session: Session) -> None:
    """Borra todas las tablas en orden compatible con las FKs.

    No toca el esquema; solo trunca los datos. Útil en dev para volver
    a un estado limpio antes de re-sembrar.
    """
    # Orden inverso al de creación para respetar FKs.
    for model in (Consulta, Cita, Horario, Medico, Paciente, Auditoria, Usuario):
        for row in session.exec(select(model)).all():
            session.delete(row)
    session.commit()
    logger.info("reset_datos: todas las tablas vaciadas")
