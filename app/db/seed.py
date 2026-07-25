"""Sistema de seeders del SGCM.

Pobla la base de datos con datos realistas del HTQPJB para que el sistema sea
usable desde el primer arranque, sin necesidad de registro manual. Todas las
funciones son idempotentes: verifican con SELECT antes de INSERT, de modo que
ejecutar el seed dos veces no duplica datos.

Generan además registros de auditoría coherentes con cada operación,
respetando el modelo de auditoría transaccional exigido por la Ley 172-13.

CONTEXTO: el seed se ejecuta por el docker-entrypoint cuando la variable
de entorno SGCM_SEED=true. En .env normalmente se deja en false para
producción y solo se pone true al hacer un demo o reset de datos.

MODELO DE "TOP-UP" (importante): los seeders NO son "todo o nada". Cada
uno compara lo que hay en la BD contra su cifra objetivo y crea sólo la
diferencia. Eso permite:
  - Ampliar el volumen del demo subiendo una constante y re-ejecutando,
    sin borrar ni duplicar lo ya existente.
  - Mantener la idempotencia: alcanzada la cifra objetivo, una segunda
    corrida no crea nada (los tests de tests/test_seed.py lo verifican).

Cifras objetivo del seed (validadas en tests):
  - 18 especialidades del catálogo CU-17 con descripción
  - 2 admins + 6 secretarias + 12 médicos con cuenta + 8 médicos sin cuenta
    (20 médicos en total: 18 activos, 2 inactivos)
  - ~220 pacientes con cédulas dominicanas válidas
  - ~2000 citas repartidas en ~5 meses de historia + ~6 semanas a futuro
  - 1 consulta por cada cita atendida (~1150)
  - ~620 registros de acceso (LOGIN) repartidos por la historia

REALISMO TEMPORAL: los timestamps NO se estampan con `ahora_local()` a lo
bruto. Una cita registrada hoy pero fechada en marzo delataría el seed en
la pantalla de auditoría. Por eso cada fila lleva la marca de tiempo que
le habría correspondido: la cita se "agendó" días antes de la fecha de
atención, la consulta se registró minutos después de la cita, y el log de
auditoría acompaña a su operación.

Para correr el seed manualmente: `docker compose exec api python -m
app.scripts.seed_db` (ver app/scripts/seed_db.py para las opciones).
"""
from __future__ import annotations

import logging
import random
from datetime import date, datetime, time, timedelta
from typing import Iterable, Optional

from sqlmodel import Session, select

from app.core.datetime_utils import TZ_DOMINICANA, ahora_local
from app.core.security import hash_password
from app.models import (
    AccionAuditoria,
    Auditoria,
    Cita,
    Consulta,
    Especialidad,
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
# El valor 20260515 es solo una fecha cualquiera; cambiarlo regenera todo
# distinto (otros nombres, otras cédulas) sin afectar la corrección.
_SEED = 20260515

# Credenciales públicas (también documentadas en README.md).
# IMPORTANTE: estas son credenciales DE DEMO/TESIS. En producción real,
# tras el primer login del admin DEBE cambiar la password. El sistema
# no lo fuerza hoy — es deuda técnica conocida.
ADMIN_EMAIL = "admin@htqpjb.gob.do"
ADMIN_PASSWORD = "Admin123!"
SECRETARIA_PASSWORD = "Secretaria123!"
MEDICO_PASSWORD = "Medico123!"

# IPs de la intranet del hospital. La auditoría real guarda
# `request.client.host`; usar un pool pequeño de direcciones LAN hace que
# la pantalla de auditoría se vea como una red de consultorios y no como
# un script corriendo en localhost.
_IPS_INTRANET = (
    "192.168.10.14", "192.168.10.21", "192.168.10.22", "192.168.10.35",
    "192.168.10.41", "192.168.20.11", "192.168.20.12", "10.0.5.7",
)


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

    Algoritmo oficial JCE (Junta Central Electoral): variante del
    algoritmo de Luhn:
      1. Multiplica cada uno de los 10 dígitos por su peso (1,2,1,2...).
      2. Si el producto >= 10, le resta 9 (equivalente a sumar sus dígitos).
      3. Suma todos los productos.
      4. El dígito verificador es (10 - suma_mod_10) % 10.

    Ejemplo: 402-12345-6 (primeros 10 = "4021234567")
       4·1=4, 0·2=0, 2·1=2, 1·2=2, 2·1=2, 3·2=6, 4·1=4, 5·2=10→1, 6·1=6, 7·2=14→5
       suma=32 → (10 - 32%10) % 10 = (10-2)%10 = 8
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

    OJO: este generador es solo para SEED — no para validar cédulas reales.
    No garantiza que el código municipal corresponda EXACTAMENTE a un
    municipio existente, solo que está en un rango plausible.
    """
    municipio = f"{rng.randint(1, 90):03d}"
    serie = f"{rng.randint(0, 9999999):07d}"
    primeros_diez = municipio + serie
    return primeros_diez + str(_digito_verificador_cedula(primeros_diez))


# ====================================================================
# Catálogos auxiliares de nombres dominicanos (fallback si Faker no rinde).
# Listas amplias a propósito: con ~220 pacientes, catálogos cortos
# producen homónimos por todas partes y el demo pierde credibilidad.
# ====================================================================
_NOMBRES_M = [
    "Juan", "Pedro", "Luis", "Carlos", "Miguel", "José", "Ramón", "Francisco",
    "Antonio", "Manuel", "Rafael", "Eduardo", "Andrés", "Domingo", "Felipe",
    "Héctor", "Julio", "Daniel", "Jorge", "Víctor", "Wilson", "Ariel",
    "Elvis", "Franklin", "Radhamés", "Fausto", "Bienvenido", "Nelson",
    "Amaury", "Cristian", "Rubén", "Gregorio", "Emilio", "Santiago",
    "Alberto", "Freddy", "Milton", "Ronny", "Alexis", "Yovanny",
]
_NOMBRES_F = [
    "María", "Ana", "Rosa", "Juana", "Elena", "Patricia", "Carmen", "Mercedes",
    "Altagracia", "Yolanda", "Sandra", "Lucía", "Marta", "Teresa", "Isabel",
    "Cristina", "Yokasta", "Damaris", "Esperanza", "Francisca", "Marisol",
    "Nurys", "Clara", "Dulce", "Yaneris", "Miguelina", "Ramona", "Josefina",
    "Andrea", "Katherine", "Yesenia", "Massiel", "Awilda", "Milagros",
    "Elizabeth", "Wendy", "Yudelka", "Ingrid", "Belkis", "Paola",
]
_APELLIDOS_RD = [
    "Pérez", "Rodríguez", "Martínez", "Santos", "García", "Fernández", "López",
    "Jiménez", "Hernández", "Sánchez", "Reyes", "Castillo", "Peña", "Cabrera",
    "Mejía", "Ramírez", "Rosario", "Núñez", "Polanco", "De los Santos",
    "Tejada", "Almonte", "Espinal", "Liriano", "Vásquez", "Guzmán", "Batista",
    "Encarnación", "Féliz", "Ureña", "Bautista", "Contreras", "Díaz", "Duarte",
    "Estévez", "Gómez", "Guerrero", "Herrera", "Lantigua", "Marte", "Medina",
    "Morales", "Paulino", "Pichardo", "Quezada", "Salcedo", "Toribio",
    "Valdez", "Ventura", "Abreu",
]
_CALLES_RD = [
    "Calle Duarte", "Avenida Mella", "Calle Sánchez", "Avenida 27 de Febrero",
    "Calle Hostos", "Avenida Independencia", "Calle Padre Billini",
    "Calle Pedro Henríquez Ureña", "Avenida Gregorio Luperón",
    "Calle El Sol", "Calle Las Carreras", "Calle Restauración",
    "Calle Colón", "Avenida Rivas", "Calle Juan Bosch",
    "Calle Profesor Emilio Prud'Homme", "Calle Cáceres", "Callejón del Rosario",
]
_SECTORES_LV = [
    "La Vega centro", "Don Bosco", "Villa Rosa", "Pueblo Nuevo",
    "Las Carolinas", "Los Pomos", "El Carmen", "La Chuchita",
    "Santo Cerro", "Barrio Lindo", "Ensanche Libertad", "Las Flores",
    "La Colonia", "Río Verde", "Villa Francisca", "Los Cacicazgos",
    "Palmarito", "El Ranchito",
]
# Municipios del Cibao a los que también sirve el HTQPJB (hospital regional).
# Un porcentaje de los pacientes viene de fuera del municipio de La Vega.
_MUNICIPIOS_CIBAO = [
    "Jarabacoa, La Vega", "Constanza, La Vega", "Jima Abajo, La Vega",
    "Rincón, La Vega", "Moca, Espaillat", "Bonao, Monseñor Nouel",
    "Cotuí, Sánchez Ramírez", "Salcedo, Hermanas Mirabal",
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
    """Dirección plausible: ~78% del municipio de La Vega, resto del Cibao."""
    numero = rng.randint(1, 250)
    calle = rng.choice(_CALLES_RD)
    if rng.random() < 0.78:
        return f"{calle} #{numero}, {rng.choice(_SECTORES_LV)}, La Vega"
    return f"{calle} #{numero}, {rng.choice(_MUNICIPIOS_CIBAO)}"


# ====================================================================
# Catálogo de especialidades (CU-17) con descripción institucional.
# DEBE coincidir con scripts/init.sql, la migración 0007 y la lista de
# tests/conftest.py. Aquí además se aporta la descripción, que init.sql
# deja en NULL — sin ella la pantalla /especialidades.html muestra una
# columna entera de guiones.
# ====================================================================
_ESPECIALIDADES_HTQPJB: tuple[tuple[str, str], ...] = (
    ("Ortopedia y Traumatología",
     "Atención de fracturas, lesiones osteomusculares y trauma del aparato locomotor."),
    ("Cirugía General",
     "Procedimientos quirúrgicos de abdomen, pared abdominal y tejidos blandos."),
    ("Cirugía Vascular",
     "Manejo quirúrgico de arterias, venas y sistema linfático periférico."),
    ("Cirugía Torácica",
     "Patología quirúrgica de pulmón, pleura, mediastino y pared torácica."),
    ("Cirugía Plástica",
     "Cirugía reconstructiva de quemaduras, cicatrices y defectos de cobertura."),
    ("Cirugía Pediátrica",
     "Procedimientos quirúrgicos en pacientes menores de 15 años."),
    ("Cirugía Ginecológica",
     "Cirugía del aparato reproductor femenino y patología uterina."),
    ("Neurocirugía",
     "Manejo quirúrgico de cráneo, columna vertebral y sistema nervioso."),
    ("Cirugía Maxilofacial",
     "Trauma y patología de macizo facial, mandíbula y cavidad oral."),
    ("Anestesiología",
     "Evaluación preanestésica, anestesia quirúrgica y manejo del dolor."),
    ("Medicina Interna",
     "Diagnóstico y tratamiento de enfermedades crónicas del adulto."),
    ("Urología",
     "Patología de vías urinarias y aparato genital masculino."),
    ("Oftalmología",
     "Evaluación y tratamiento de la agudeza visual y patología ocular."),
    ("Otorrinolaringología",
     "Atención de oído, nariz, senos paranasales, faringe y laringe."),
    ("Medicina Física y Rehabilitación",
     "Terapia física, rehabilitación funcional y manejo del dolor crónico."),
    ("Radiología y Diagnóstico por Imágenes",
     "Estudios de imagen: radiografía, sonografía y tomografía."),
    ("Laboratorio Clínico",
     "Procesamiento de muestras y estudios de laboratorio de apoyo diagnóstico."),
    ("Emergenciología",
     "Atención inicial de urgencias médicas y quirúrgicas del hospital."),
)


# ====================================================================
# Plantillas clínicas por especialidad (para seed_consultas).
# Varias por especialidad: con ~1150 consultas, una sola plantilla haría
# que todos los historiales del hospital dijeran exactamente lo mismo.
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
        {
            "motivo_consulta": "Control post-operatorio de fractura de radio distal",
            "examen_fisico": "Herida quirúrgica limpia, sin secreción, movilidad de dedos conservada",
            "condicion_principal": "S52.501 Fractura de extremo distal de radio derecho, en consolidación",
            "tratamiento": "Retiro de puntos, inicio de fisioterapia, radiografía control en 30 días",
        },
        {
            "motivo_consulta": "Dolor lumbar irradiado a miembro inferior derecho",
            "examen_fisico": "Lasègue positivo a 45 grados, reflejos conservados",
            "condicion_principal": "M51.16 Hernia discal lumbar con radiculopatía",
            "tratamiento": "Relajante muscular, pregabalina 75 mg nocturna, resonancia lumbar",
        },
        {
            "motivo_consulta": "Accidente de motocicleta con trauma en hombro izquierdo",
            "examen_fisico": "Deformidad clavicular, crepitación, pulsos distales presentes",
            "condicion_principal": "S42.002 Fractura de clavícula izquierda",
            "tratamiento": "Inmovilizador en ocho por 4 semanas, analgesia, control semanal",
        },
    ],
    "Cirugía General": [
        {
            "motivo_consulta": "Dolor abdominal en fosa ilíaca derecha de 24 horas",
            "examen_fisico": "Blumberg positivo, defensa muscular leve",
            "condicion_principal": "K35.80 Apendicitis aguda, no especificada",
            "tratamiento": "Ingreso para apendicectomía, antibioticoterapia preoperatoria",
        },
        {
            "motivo_consulta": "Dolor en hipocondrio derecho tras comidas grasas",
            "examen_fisico": "Murphy positivo, sin ictericia, ruidos hidroaéreos presentes",
            "condicion_principal": "K80.20 Colelitiasis sin colecistitis",
            "tratamiento": "Dieta hipograsa, programar colecistectomía laparoscópica electiva",
        },
        {
            "motivo_consulta": "Aumento de volumen en región inguinal derecha",
            "examen_fisico": "Tumoración reductible, aumenta con Valsalva, no dolorosa",
            "condicion_principal": "K40.90 Hernia inguinal derecha no complicada",
            "tratamiento": "Programar hernioplastia con malla, evitar esfuerzos físicos",
        },
        {
            "motivo_consulta": "Control post-operatorio de colecistectomía",
            "examen_fisico": "Puertos laparoscópicos cicatrizados, abdomen blando, depresible",
            "condicion_principal": "Z48.815 Atención posterior a cirugía del sistema digestivo",
            "tratamiento": "Alta de seguimiento quirúrgico, reintegro laboral progresivo",
        },
    ],
    "Cirugía Vascular": [
        {
            "motivo_consulta": "Várices dolorosas en miembro inferior derecho",
            "examen_fisico": "Várices tronculares visibles, sin signos de trombosis",
            "condicion_principal": "I83.90 Várices de miembros inferiores",
            "tratamiento": "Medias compresivas, evaluación para escleroterapia",
        },
        {
            "motivo_consulta": "Dolor en pantorrilla al caminar dos cuadras",
            "examen_fisico": "Pulsos pedios disminuidos, llenado capilar 3 segundos",
            "condicion_principal": "I73.9 Enfermedad arterial periférica",
            "tratamiento": "Cilostazol 100 mg cada 12 horas, cese de tabaco, doppler arterial",
        },
        {
            "motivo_consulta": "Úlcera que no cierra en maléolo interno",
            "examen_fisico": "Úlcera de 3 cm, bordes irregulares, tejido de granulación",
            "condicion_principal": "I83.008 Úlcera venosa de miembro inferior",
            "tratamiento": "Curaciones cada 48 horas, terapia compresiva, control en 15 días",
        },
    ],
    "Cirugía Torácica": [
        {
            "motivo_consulta": "Dolor torácico persistente con disnea leve",
            "examen_fisico": "Ruidos respiratorios disminuidos en base izquierda",
            "condicion_principal": "J93.0 Neumotórax espontáneo",
            "tratamiento": "Radiografía de tórax control, evaluación para drenaje pleural",
        },
        {
            "motivo_consulta": "Trauma torácico cerrado por accidente de tránsito",
            "examen_fisico": "Crepitación en arcos costales derechos, saturación 94%",
            "condicion_principal": "S22.39 Fractura costal múltiple derecha",
            "tratamiento": "Analgesia escalonada, fisioterapia respiratoria, control en 72 horas",
        },
        {
            "motivo_consulta": "Tos persistente con hallazgo radiológico anormal",
            "examen_fisico": "Murmullo vesicular conservado, no adenopatías palpables",
            "condicion_principal": "R91.8 Hallazgo anormal en imagen de pulmón",
            "tratamiento": "Tomografía de tórax contrastada, evaluación multidisciplinaria",
        },
    ],
    "Cirugía Plástica": [
        {
            "motivo_consulta": "Cicatriz hipertrófica en antebrazo post-quemadura",
            "examen_fisico": "Cicatriz elevada, eritematosa, sin signos de infección",
            "condicion_principal": "L91.0 Cicatriz hipertrófica",
            "tratamiento": "Láminas de silicona, control en 30 días",
        },
        {
            "motivo_consulta": "Herida en dorso de mano con pérdida de cobertura",
            "examen_fisico": "Lecho cruento de 4 cm, tendones extensores íntegros",
            "condicion_principal": "S61.409 Herida abierta de mano con pérdida cutánea",
            "tratamiento": "Programar injerto de espesor parcial, curaciones diarias",
        },
        {
            "motivo_consulta": "Quemadura de segundo grado en antebrazo por aceite",
            "examen_fisico": "Flictenas en 4% de superficie corporal, dolor intenso",
            "condicion_principal": "T22.29 Quemadura de segundo grado de antebrazo",
            "tratamiento": "Sulfadiazina de plata, curación cada 48 horas, analgesia",
        },
    ],
    "Cirugía Pediátrica": [
        {
            "motivo_consulta": "Tumoración inguinal derecha en niño de 4 años",
            "examen_fisico": "Hernia inguinal reductible, sin signos de incarceración",
            "condicion_principal": "K40.90 Hernia inguinal unilateral",
            "tratamiento": "Programar herniorrafia electiva, vigilancia familiar",
        },
        {
            "motivo_consulta": "Testículo no palpable en escroto derecho",
            "examen_fisico": "Teste derecho en canal inguinal, izquierdo normoposicionado",
            "condicion_principal": "Q53.10 Criptorquidia unilateral",
            "tratamiento": "Sonografía inguinal, programar orquidopexia",
        },
        {
            "motivo_consulta": "Control post-operatorio de apendicectomía en escolar",
            "examen_fisico": "Herida limpia y seca, abdomen blando, tolera vía oral",
            "condicion_principal": "Z48.812 Atención posterior a cirugía abdominal",
            "tratamiento": "Retiro de puntos, reintegro escolar en una semana",
        },
    ],
    "Cirugía Ginecológica": [
        {
            "motivo_consulta": "Sangrado uterino anormal de 3 meses de evolución",
            "examen_fisico": "Útero aumentado de tamaño, móvil, no doloroso",
            "condicion_principal": "D25.9 Leiomioma del útero, no especificado",
            "tratamiento": "Solicitar sonografía pélvica, control en 21 días",
        },
        {
            "motivo_consulta": "Dolor pélvico crónico de un año de evolución",
            "examen_fisico": "Dolor a la movilización cervical, anexos sin masas palpables",
            "condicion_principal": "N80.9 Endometriosis no especificada",
            "tratamiento": "Analgesia hormonal, evaluación para laparoscopia diagnóstica",
        },
        {
            "motivo_consulta": "Masa anexial detectada en sonografía de rutina",
            "examen_fisico": "Abdomen blando, masa anexial izquierda de 5 cm, móvil",
            "condicion_principal": "N83.209 Quiste ovárico no especificado",
            "tratamiento": "Marcadores tumorales, sonografía control en 8 semanas",
        },
    ],
    "Neurocirugía": [
        {
            "motivo_consulta": "Cefalea progresiva con vómitos matutinos",
            "examen_fisico": "Fondo de ojo: edema de papila incipiente",
            "condicion_principal": "G93.2 Hipertensión intracraneal benigna",
            "tratamiento": "TAC craneal urgente, acetazolamida 250 mg cada 12 horas",
        },
        {
            "motivo_consulta": "Trauma craneoencefálico leve por caída de altura",
            "examen_fisico": "Glasgow 15, sin focalización neurológica, herida en cuero cabelludo",
            "condicion_principal": "S06.0X0 Concusión sin pérdida de conciencia",
            "tratamiento": "Observación domiciliaria, signos de alarma explicados, control en 7 días",
        },
        {
            "motivo_consulta": "Dolor cervical con hormigueo en mano derecha",
            "examen_fisico": "Spurling positivo derecho, fuerza 4/5 en extensores de muñeca",
            "condicion_principal": "M50.121 Hernia discal cervical con radiculopatía",
            "tratamiento": "Collarín blando, gabapentina 300 mg nocturna, resonancia cervical",
        },
    ],
    "Cirugía Maxilofacial": [
        {
            "motivo_consulta": "Trauma facial por accidente de tránsito",
            "examen_fisico": "Crepitación malar derecha, equimosis periorbitaria",
            "condicion_principal": "S02.40 Fractura malar y maxilar",
            "tratamiento": "TAC facial, dieta blanda, evaluación para osteosíntesis",
        },
        {
            "motivo_consulta": "Dolor y limitación para abrir la boca tras golpe",
            "examen_fisico": "Apertura bucal de 20 mm, dolor preauricular derecho",
            "condicion_principal": "S02.609 Fractura de mandíbula no especificada",
            "tratamiento": "Bloqueo intermaxilar, dieta líquida, control semanal",
        },
        {
            "motivo_consulta": "Aumento de volumen submandibular de una semana",
            "examen_fisico": "Tumefacción dolorosa, sin fluctuación, trismus leve",
            "condicion_principal": "K12.2 Celulitis del piso de boca",
            "tratamiento": "Amoxicilina con ácido clavulánico 875 mg cada 12 horas, control en 48 horas",
        },
    ],
    "Anestesiología": [
        {
            "motivo_consulta": "Evaluación preanestésica para colecistectomía electiva",
            "examen_fisico": "Vía aérea Mallampati II, ASA II",
            "condicion_principal": "Z01.818 Evaluación preoperatoria",
            "tratamiento": "Apto para anestesia general, ayuno 8 horas previas",
        },
        {
            "motivo_consulta": "Valoración preanestésica en paciente hipertenso",
            "examen_fisico": "TA 138/86 controlada, Mallampati I, sin soplos",
            "condicion_principal": "Z01.812 Evaluación preoperatoria cardiovascular",
            "tratamiento": "Continuar antihipertensivo la mañana de cirugía, ASA II, apto",
        },
        {
            "motivo_consulta": "Consulta de clínica del dolor por lumbalgia refractaria",
            "examen_fisico": "Dolor 7/10 en escala visual análoga, sin déficit motor",
            "condicion_principal": "G89.29 Dolor crónico no especificado",
            "tratamiento": "Bloqueo facetario lumbar programado, ajuste de analgesia",
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
        {
            "motivo_consulta": "Control de diabetes e hipertensión de 5 años",
            "examen_fisico": "TA 132/80, peso estable, pies sin lesiones",
            "condicion_principal": "E11.9 Diabetes mellitus tipo 2 en control",
            "tratamiento": "Mantener esquema actual, HbA1c trimestral, evaluación oftalmológica anual",
        },
        {
            "motivo_consulta": "Fatiga y palidez de un mes de evolución",
            "examen_fisico": "Palidez conjuntival, taquicardia leve, sin visceromegalia",
            "condicion_principal": "D50.9 Anemia por deficiencia de hierro",
            "tratamiento": "Sulfato ferroso 300 mg cada 12 horas, hemograma control en 30 días",
        },
    ],
    "Urología": [
        {
            "motivo_consulta": "Disuria y polaquiuria de 3 días",
            "examen_fisico": "Puño percusión renal negativa, sin globo vesical",
            "condicion_principal": "N39.0 Infección de vías urinarias",
            "tratamiento": "Ciprofloxacina 500 mg cada 12 horas por 7 días",
        },
        {
            "motivo_consulta": "Dolor lumbar cólico con hematuria",
            "examen_fisico": "Puño percusión renal derecha positiva, abdomen blando",
            "condicion_principal": "N20.0 Cálculo renal derecho",
            "tratamiento": "Hidratación abundante, tamsulosina 0.4 mg, sonografía renal",
        },
        {
            "motivo_consulta": "Dificultad para iniciar la micción en varón de 68 años",
            "examen_fisico": "Próstata aumentada grado II, consistencia elástica",
            "condicion_principal": "N40.1 Hiperplasia prostática con síntomas urinarios",
            "tratamiento": "Tamsulosina 0.4 mg nocturna, PSA y sonografía prostática",
        },
    ],
    "Oftalmología": [
        {
            "motivo_consulta": "Visión borrosa progresiva de cerca",
            "examen_fisico": "Agudeza visual J5, fondo de ojo normal",
            "condicion_principal": "H52.4 Presbicia",
            "tratamiento": "Corrección óptica con lentes para lectura +1.50",
        },
        {
            "motivo_consulta": "Disminución de visión en ojo derecho de un año",
            "examen_fisico": "Opacidad de cristalino derecho, agudeza visual 20/100",
            "condicion_principal": "H25.11 Catarata senil nuclear del ojo derecho",
            "tratamiento": "Programar facoemulsificación con lente intraocular",
        },
        {
            "motivo_consulta": "Ojo rojo con secreción de 3 días",
            "examen_fisico": "Hiperemia conjuntival bilateral, córnea transparente",
            "condicion_principal": "H10.023 Conjuntivitis aguda bilateral",
            "tratamiento": "Tobramicina colirio cada 6 horas por 7 días, higiene palpebral",
        },
        {
            "motivo_consulta": "Control de retinopatía en paciente diabético",
            "examen_fisico": "Microaneurismas dispersos, mácula sin edema",
            "condicion_principal": "E11.319 Retinopatía diabética no proliferativa",
            "tratamiento": "Control estricto de glicemia, fondo de ojo en 6 meses",
        },
    ],
    "Otorrinolaringología": [
        {
            "motivo_consulta": "Otalgia derecha tras baño en piscina",
            "examen_fisico": "Conducto auditivo eritematoso, tímpano íntegro",
            "condicion_principal": "H60.391 Otitis externa, oído derecho",
            "tratamiento": "Ciprofloxacina ótica 3 gotas cada 8 horas por 7 días",
        },
        {
            "motivo_consulta": "Obstrucción nasal crónica y ronquido",
            "examen_fisico": "Desviación septal derecha, cornetes hipertróficos",
            "condicion_principal": "J34.2 Desviación del tabique nasal",
            "tratamiento": "Corticoide nasal 2 aplicaciones diarias, evaluación para septoplastia",
        },
        {
            "motivo_consulta": "Dolor de garganta recurrente, cuarto episodio del año",
            "examen_fisico": "Amígdalas hipertróficas grado III con criptas",
            "condicion_principal": "J35.01 Amigdalitis crónica",
            "tratamiento": "Programar amigdalectomía electiva, analgesia en crisis",
        },
    ],
    "Medicina Física y Rehabilitación": [
        {
            "motivo_consulta": "Lumbalgia crónica de 2 meses",
            "examen_fisico": "Contractura paravertebral L4-L5, Lasègue negativo",
            "condicion_principal": "M54.5 Lumbago no especificado",
            "tratamiento": "10 sesiones de fisioterapia, ejercicios de Williams",
        },
        {
            "motivo_consulta": "Rigidez de hombro derecho posterior a inmovilización",
            "examen_fisico": "Abducción limitada a 90 grados, dolor en arco medio",
            "condicion_principal": "M75.01 Capsulitis adhesiva de hombro derecho",
            "tratamiento": "15 sesiones de terapia física, ejercicios pendulares en casa",
        },
        {
            "motivo_consulta": "Rehabilitación posterior a evento cerebrovascular",
            "examen_fisico": "Hemiparesia izquierda 3/5, marcha con apoyo",
            "condicion_principal": "I69.354 Hemiplejía secuelar de infarto cerebral",
            "tratamiento": "Terapia física y ocupacional 3 veces por semana, control mensual",
        },
    ],
    "Radiología y Diagnóstico por Imágenes": [
        {
            "motivo_consulta": "Estudio sonográfico abdominal por dolor recurrente",
            "examen_fisico": "Abdomen blando, doloroso a la palpación profunda",
            "condicion_principal": "R10.9 Dolor abdominal no especificado",
            "tratamiento": "Sonografía abdominal completa, control con resultados",
        },
        {
            "motivo_consulta": "Radiografía de control de fractura consolidada",
            "examen_fisico": "Sin dolor a la palpación, movilidad conservada",
            "condicion_principal": "Z09 Examen de control posterior a tratamiento",
            "tratamiento": "Radiografía en dos proyecciones, informe entregado al traumatólogo",
        },
        {
            "motivo_consulta": "Sonografía obstétrica de segundo trimestre",
            "examen_fisico": "Altura uterina acorde, foco fetal presente",
            "condicion_principal": "Z36.3 Tamizaje prenatal por imagen",
            "tratamiento": "Sonografía morfológica realizada, resultados a ginecología",
        },
    ],
    "Laboratorio Clínico": [
        {
            "motivo_consulta": "Solicitud de perfil de control anual",
            "examen_fisico": "Paciente asintomático",
            "condicion_principal": "Z00.00 Examen médico general sin anormalidades",
            "tratamiento": "Hemograma, glicemia, perfil lipídico, perfil renal",
        },
        {
            "motivo_consulta": "Analítica preoperatoria solicitada por cirugía",
            "examen_fisico": "Paciente estable, sin signos de infección activa",
            "condicion_principal": "Z01.812 Examen de laboratorio preoperatorio",
            "tratamiento": "Hemograma, coagulograma, tipificación y glicemia en ayunas",
        },
        {
            "motivo_consulta": "Control de hemoglobina glicosilada en diabético",
            "examen_fisico": "Paciente en buen estado general",
            "condicion_principal": "Z13.1 Tamizaje de diabetes mellitus",
            "tratamiento": "HbA1c y microalbuminuria, resultados a medicina interna",
        },
    ],
    "Emergenciología": [
        {
            "motivo_consulta": "Fiebre y malestar general de 24 horas",
            "examen_fisico": "T° 38.7, faringe eritematosa, no exudado",
            "condicion_principal": "J06.9 Infección aguda de vías respiratorias superiores",
            "tratamiento": "Acetaminofén 500 mg cada 6 horas, abundante líquido",
        },
        {
            "motivo_consulta": "Herida cortante en antebrazo por vidrio",
            "examen_fisico": "Herida de 5 cm, bordes limpios, sin compromiso tendinoso",
            "condicion_principal": "S51.812 Herida cortante de antebrazo izquierdo",
            "tratamiento": "Sutura con nylon 4-0, toxoide tetánico, retiro de puntos en 8 días",
        },
        {
            "motivo_consulta": "Dolor abdominal difuso con vómitos de 12 horas",
            "examen_fisico": "Abdomen blando, doloroso difusamente, sin irritación peritoneal",
            "condicion_principal": "K52.9 Gastroenteritis aguda no especificada",
            "tratamiento": "Hidratación oral, metoclopramida si vómito, control en 24 horas",
        },
        {
            "motivo_consulta": "Crisis hipertensiva con cefalea intensa",
            "examen_fisico": "TA 190/110, sin focalización neurológica",
            "condicion_principal": "I16.0 Urgencia hipertensiva",
            "tratamiento": "Captopril 25 mg sublingual, observación 4 horas, referir a medicina interna",
        },
    ],
}

_PLANTILLA_GENERICA = {
    "motivo_consulta": "Control médico de rutina",
    "examen_fisico": "Paciente en buen estado general, signos vitales estables",
    "condicion_principal": "Z00.00 Examen médico general sin hallazgos relevantes",
    "tratamiento": "Continuar con régimen habitual, control en 6 meses",
}

# Comorbilidades frecuentes en la población dominicana. Se añaden como
# condiciones secundarias en ~35% de las consultas: un historial donde
# NADIE tiene comorbilidad se ve fabricado.
_CONDICIONES_SECUNDARIAS = (
    "I10 Hipertensión esencial en tratamiento",
    "E11.9 Diabetes mellitus tipo 2",
    "E66.9 Obesidad no especificada",
    "E78.5 Dislipidemia",
    "J45.909 Asma bronquial no complicada",
    "M15.9 Osteoartrosis generalizada",
    "F41.9 Trastorno de ansiedad",
    "K21.9 Enfermedad por reflujo gastroesofágico",
    "N18.3 Enfermedad renal crónica estadio 3",
    "Z87.891 Antecedente de tabaquismo",
)

_MOTIVOS_CITA_GENERICOS = [
    "Consulta de seguimiento",
    "Primera consulta",
    "Control post-operatorio",
    "Evaluación por especialista",
    "Revisión de exámenes",
    "Renovación de tratamiento",
    "Referimiento desde emergencia",
    "Control de tratamiento crónico",
    "Evaluación preoperatoria",
    "Retiro de puntos",
    "Chequeo anual",
    "Referimiento desde UNAP",
]


# ====================================================================
# Helpers de tiempo y auditoría.
# ====================================================================
def _aware(fecha: date, hora: time) -> datetime:
    """Combina fecha + hora en un datetime AWARE de zona dominicana.

    OJO: las columnas temporales del SGCM son TIMESTAMPTZ. Insertar un
    datetime naive haría que PostgreSQL lo interprete como UTC y todos
    los timestamps del seed aparecerían 4 horas corridos.
    """
    return datetime.combine(fecha, hora, tzinfo=TZ_DOMINICANA)


def _como_aware(dt: Optional[datetime], defecto: datetime) -> datetime:
    """Normaliza a datetime aware; `defecto` cubre el caso None.

    CUIDADO: hace falta porque los tests corren sobre SQLite, que no
    guarda zona horaria: un timestamp que se escribió aware vuelve NAIVE
    al releerlo, y compararlo con `ahora_local()` revienta con
    "can't compare offset-naive and offset-aware datetimes". PostgreSQL
    (TIMESTAMPTZ) sí lo devuelve aware, así que el bug solo aparece en
    la suite — razón de más para normalizar en un único sitio.
    """
    if dt is None:
        return defecto
    return dt if dt.tzinfo else dt.replace(tzinfo=TZ_DOMINICANA)


def _audit(
    session: Session,
    actor: Optional[Usuario],
    accion: AccionAuditoria,
    tabla: str,
    id_registro: Optional[int],
    detalle: str,
    cuando: Optional[datetime] = None,
    ip_origen: Optional[str] = None,
) -> None:
    """Añade un registro de auditoría a la sesión SIN commit.

    `cuando` permite fechar el log en el momento en que la operación
    habría ocurrido de verdad (la cita se agendó en marzo, no hoy). Si se
    omite, se usa el instante actual — mismo comportamiento que
    app/services/audit.py para operaciones en vivo.

    CUIDADO: `cuando` se recorta a "ahora". Una bitácora no puede tener
    entradas del futuro, y la pantalla de auditoría ordena por fecha_hora
    DESC — una fila adelantada se quedaría clavada en el tope de la lista.
    """
    ahora = ahora_local()
    cuando = min(_como_aware(cuando, ahora), ahora)
    log = Auditoria(
        id_usuario=actor.id if actor else None,
        nombre_usuario=actor.nombre if actor else "[seed]",
        accion=accion,
        tabla_afectada=tabla,
        id_registro=id_registro,
        detalle=detalle,
        ip_origen=ip_origen or "127.0.0.1",
        fecha_hora=cuando,
    )
    session.add(log)


# ====================================================================
# Configuración declarativa de usuarios.
# `_dias_antiguedad` fija hace cuántos días se dio de alta la cuenta:
# un hospital que lleva meses operando no tiene a todo el personal
# creado el mismo día.
# ====================================================================
_USUARIOS_BASE: list[dict] = [
    # Administradores
    {
        "email": ADMIN_EMAIL,
        "nombre": "Administrador SGCM",
        "password": ADMIN_PASSWORD,
        "rol": RolUsuario.admin,
        "activo": True,
        "_dias_antiguedad": 430,
    },
    {
        "email": "soporte.ti@htqpjb.gob.do",
        "nombre": "Soporte TI HTQPJB",
        "password": ADMIN_PASSWORD,
        "rol": RolUsuario.admin,
        "activo": True,
        "_dias_antiguedad": 260,
    },
    # Secretarias (6: 5 activas + 1 dada de baja)
    {
        "email": "secretaria.maria@htqpjb.gob.do",
        "nombre": "María Fernández",
        "password": SECRETARIA_PASSWORD,
        "rol": RolUsuario.secretaria,
        "activo": True,
        "_dias_antiguedad": 425,
    },
    {
        "email": "secretaria.juana@htqpjb.gob.do",
        "nombre": "Juana Rodríguez",
        "password": SECRETARIA_PASSWORD,
        "rol": RolUsuario.secretaria,
        "activo": True,
        "_dias_antiguedad": 410,
    },
    {
        "email": "secretaria.elena@htqpjb.gob.do",
        "nombre": "Elena Martínez",
        "password": SECRETARIA_PASSWORD,
        "rol": RolUsuario.secretaria,
        "activo": True,
        "_dias_antiguedad": 360,
    },
    {
        "email": "secretaria.rosa@htqpjb.gob.do",
        "nombre": "Rosa Peña",
        "password": SECRETARIA_PASSWORD,
        "rol": RolUsuario.secretaria,
        "activo": True,
        "_dias_antiguedad": 300,
    },
    {
        "email": "secretaria.yaneris@htqpjb.gob.do",
        "nombre": "Yaneris Almonte",
        "password": SECRETARIA_PASSWORD,
        "rol": RolUsuario.secretaria,
        "activo": True,
        "_dias_antiguedad": 150,
    },
    {
        "email": "secretaria.baja@htqpjb.gob.do",
        "nombre": "Miguelina Ureña",
        "password": SECRETARIA_PASSWORD,
        "rol": RolUsuario.secretaria,
        "activo": False,  # Dada de baja — prueba el soft delete de usuarios
        "_dias_antiguedad": 395,
    },
    # Médicos con cuenta de sistema (11 activos + 1 inactivo)
    {
        "email": "dr.jperez@htqpjb.gob.do",
        "nombre": "Dr. Juan Pérez",
        "password": MEDICO_PASSWORD,
        "rol": RolUsuario.medico,
        "activo": True,
        "_especialidad": "Ortopedia y Traumatología",
        "_secundarias": (),
        "_telefono": "809-555-0101",
        "_patron": "completo",
        "_dias_antiguedad": 428,
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
        "_patron": "completo",
        "_dias_antiguedad": 424,
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
        "_patron": "completo",
        "_dias_antiguedad": 420,
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
        "_patron": "completo",
        "_dias_antiguedad": 405,
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
        "_patron": "completo",
        "_dias_antiguedad": 390,
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
        "_patron": "matutino",
        "_dias_antiguedad": 415,
    },
    {
        "email": "dr.fmarte@htqpjb.gob.do",
        "nombre": "Dr. Franklin Marte",
        "password": MEDICO_PASSWORD,
        "rol": RolUsuario.medico,
        "activo": True,
        "_especialidad": "Ortopedia y Traumatología",
        "_secundarias": ("Medicina Física y Rehabilitación",),
        "_telefono": "809-555-0107",
        "_patron": "alterno_lmv",
        "_dias_antiguedad": 340,
    },
    {
        "email": "dra.mcabrera@htqpjb.gob.do",
        "nombre": "Dra. Marisol Cabrera",
        "password": MEDICO_PASSWORD,
        "rol": RolUsuario.medico,
        "activo": True,
        "_especialidad": "Cirugía Ginecológica",
        "_secundarias": (),
        "_telefono": "809-555-0108",
        "_patron": "matutino",
        "_dias_antiguedad": 320,
    },
    {
        "email": "dr.aguzman@htqpjb.gob.do",
        "nombre": "Dr. Amaury Guzmán",
        "password": MEDICO_PASSWORD,
        "rol": RolUsuario.medico,
        "activo": True,
        "_especialidad": "Emergenciología",
        "_secundarias": ("Medicina Interna",),
        "_telefono": "809-555-0109",
        "_patron": "guardia",
        "_dias_antiguedad": 295,
    },
    {
        "email": "dra.kbatista@htqpjb.gob.do",
        "nombre": "Dra. Katherine Batista",
        "password": MEDICO_PASSWORD,
        "rol": RolUsuario.medico,
        "activo": True,
        "_especialidad": "Cirugía Plástica",
        "_secundarias": ("Cirugía General",),
        "_telefono": "809-555-0110",
        "_patron": "alterno_mj",
        "_dias_antiguedad": 250,
    },
    {
        "email": "dr.gvasquez@htqpjb.gob.do",
        "nombre": "Dr. Gregorio Vásquez",
        "password": MEDICO_PASSWORD,
        "rol": RolUsuario.medico,
        "activo": True,
        "_especialidad": "Cirugía Vascular",
        "_secundarias": (),
        "_telefono": "809-555-0111",
        "_patron": "quirurgico",
        "_dias_antiguedad": 205,
    },
    {
        "email": "dra.emedina@htqpjb.gob.do",
        "nombre": "Dra. Elizabeth Medina",
        "password": MEDICO_PASSWORD,
        "rol": RolUsuario.medico,
        "activo": True,
        "_especialidad": "Medicina Interna",
        "_secundarias": (),
        "_telefono": "809-555-0112",
        "_patron": "vespertino",
        "_dias_antiguedad": 130,
    },
]


# ====================================================================
# Médicos extra (sin usuario vinculado) — cubren el resto del catálogo.
# En el HTQPJB hay especialistas que no operan el sistema: la secretaria
# les agenda y ellos firman en papel. Son ciudadanos de primera clase
# del modelo (medicos.id_usuario es NULLABLE a propósito).
# ====================================================================
_MEDICOS_SIN_USUARIO: list[dict] = [
    {
        "nombre": "Dr. Miguel Hernández",
        "especialidad": "Otorrinolaringología",
        "_secundarias": ("Emergenciología",),
        "telefono": "809-555-0201",
        "activo": True,
        "_patron": "completo",
    },
    {
        "nombre": "Dra. Patricia Mejía",
        "especialidad": "Medicina Física y Rehabilitación",
        "_secundarias": (),
        "telefono": "809-555-0202",
        "activo": True,
        "_patron": "completo",
    },
    {
        "nombre": "Dr. Héctor Tejada",
        "especialidad": "Cirugía Pediátrica",
        "_secundarias": ("Cirugía Plástica",),
        "telefono": "809-555-0203",
        "activo": True,
        "_patron": "completo",
    },
    {
        "nombre": "Dra. Yolanda Reyes",
        "especialidad": "Anestesiología",
        "_secundarias": (),
        "telefono": "809-555-0204",
        "activo": False,  # Médico inactivo (sin usuario)
        "_patron": "matutino",
    },
    {
        "nombre": "Dr. Radhamés Polanco",
        "especialidad": "Cirugía Torácica",
        "_secundarias": ("Cirugía General",),
        "telefono": "809-555-0205",
        "activo": True,
        "_patron": "quirurgico",
    },
    {
        "nombre": "Dra. Nurys Liriano",
        "especialidad": "Cirugía Maxilofacial",
        "_secundarias": (),
        "telefono": "809-555-0206",
        "activo": True,
        "_patron": "alterno_mj",
    },
    {
        "nombre": "Dr. Wilson Espinal",
        "especialidad": "Radiología y Diagnóstico por Imágenes",
        "_secundarias": (),
        "telefono": "809-555-0207",
        "activo": True,
        "_patron": "apoyo",
    },
    {
        "nombre": "Dra. Belkis Toribio",
        "especialidad": "Laboratorio Clínico",
        "_secundarias": (),
        "telefono": "809-555-0208",
        "activo": True,
        "_patron": "apoyo",
    },
]


# ====================================================================
# seed_especialidades
# ====================================================================
def seed_especialidades(session: Session) -> int:
    """Garantiza el catálogo CU-17 completo y con descripción.

    En despliegue real las 18 filas las inserta scripts/init.sql, pero
    sin descripción (queda NULL) y solo la primera vez que se crea el
    volumen. Este seeder cubre ambos huecos:
      - Crea las que falten (BD levantada sin init.sql, p. ej. SQLite).
      - Rellena `descripcion` cuando está vacía, para que la pantalla
        /especialidades.html no muestre una columna entera de guiones.

    NO desactiva ni renombra nada existente — si el admin editó una
    especialidad desde el panel, su cambio se respeta.
    """
    existentes = {e.nombre: e for e in session.exec(select(Especialidad)).all()}

    nuevas = 0
    descritas = 0
    for nombre, descripcion in _ESPECIALIDADES_HTQPJB:
        esp = existentes.get(nombre)
        if esp is None:
            session.add(Especialidad(nombre=nombre, descripcion=descripcion, activa=True))
            nuevas += 1
        elif not esp.descripcion:
            esp.descripcion = descripcion
            session.add(esp)
            descritas += 1

    session.commit()
    logger.info(
        "seed_especialidades: %d nueva(s), %d con descripción añadida", nuevas, descritas
    )
    return nuevas


# ====================================================================
# seed_usuarios
# ====================================================================
def seed_usuarios(session: Session) -> dict[str, Usuario]:
    """Crea el conjunto base de usuarios. Devuelve mapa email -> Usuario.

    Idempotente: cada usuario se busca por email antes de crearse.

    Audita CADA alta con el admin como actor (incluso el alta del propio
    admin, que aparece como auto-creado). En la primera ejecución todo
    queda registrado; en re-ejecuciones no se crea nada nuevo y no se
    audita nada nuevo.

    La `fecha_creacion` se retrocede según `_dias_antiguedad` para que el
    reporte de usuarios muestre altas escalonadas en el tiempo y no un
    bloque de 20 cuentas creadas el mismo minuto.
    """
    creados: dict[str, Usuario] = {}
    nuevos: list[Usuario] = []
    ahora = ahora_local()

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
            fecha_creacion=ahora - timedelta(days=cfg.get("_dias_antiguedad", 30)),
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
            cuando=u.fecha_creacion,
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

    OJO: `nombre.removeprefix("Dr. ").removeprefix("Dra. ")` — el campo
    `medicos.nombre` se almacena SIN el prefijo "Dr./Dra." porque ese
    prefijo es presentacional. El frontend lo reañade para mostrar. Si
    se guardara con prefijo, las búsquedas tendrían que normalizar y la
    auditoría se ensuciaría.
    """
    if usuarios is None:
        usuarios = {u.email: u for u in session.exec(select(Usuario)).all()}

    admin = usuarios.get(ADMIN_EMAIL)
    nuevos: list[Medico] = []
    creado_en: dict[int, datetime] = {}

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
        session.flush()
        creado_en[m.id] = usuario.fecha_creacion

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
            cuando=creado_en.get(m.id),
        )

    session.commit()
    todos = session.exec(select(Medico)).all()
    logger.info("seed_medicos: %d nuevo(s), %d total(es)", len(nuevos), len(todos))
    return list(todos)


# ====================================================================
# seed_horarios
# ====================================================================
# Patrones de atención del HTQPJB. Cada tupla es (dia_semana ISO,
# hora_inicio, hora_fin) y cada fila termina siendo UN registro de
# `horarios`. Un médico que parte el día en mañana y tarde produce dos
# filas para el mismo día — así lo exige el modelo (ver Horario).
#
# Que no todos los médicos compartan el mismo patrón es intencional:
# la pantalla de disponibilidad y el calendario deben mostrar médicos
# atendiendo en franjas distintas, como en un hospital real.
_HORARIOS_BASE: tuple[tuple[int, time, time], ...] = (
    (1, time(7, 0), time(12, 0)), (1, time(14, 0), time(17, 0)),  # Lunes
    (2, time(7, 0), time(12, 0)), (2, time(14, 0), time(17, 0)),  # Martes
    (3, time(7, 0), time(12, 0)), (3, time(14, 0), time(17, 0)),  # Miércoles
    (4, time(7, 0), time(12, 0)), (4, time(14, 0), time(17, 0)),  # Jueves
    (5, time(7, 0), time(12, 0)), (5, time(14, 0), time(17, 0)),  # Viernes
    (6, time(8, 0), time(12, 0)),                                  # Sábado
    # Domingo: sin atención
)

_PATRONES_HORARIO: dict[str, tuple[tuple[int, time, time], ...]] = {
    # Jornada institucional completa (mañana + tarde + sábado).
    "completo": _HORARIOS_BASE,
    # Consulta externa de mañana, lunes a viernes.
    "matutino": tuple((d, time(8, 0), time(13, 0)) for d in range(1, 6)),
    # Turno de tarde — descongestiona la consulta externa.
    "vespertino": tuple((d, time(13, 0), time(18, 0)) for d in range(2, 7)),
    # Lunes/miércoles/viernes: consulta; martes y jueves en quirófano.
    "alterno_lmv": (
        (1, time(7, 0), time(12, 0)), (1, time(14, 0), time(16, 0)),
        (3, time(7, 0), time(12, 0)), (3, time(14, 0), time(16, 0)),
        (5, time(7, 0), time(12, 0)),
    ),
    # Martes/jueves de consulta + sábado de mañana.
    "alterno_mj": (
        (2, time(7, 30), time(12, 30)),
        (4, time(7, 30), time(12, 30)), (4, time(14, 0), time(17, 0)),
        (6, time(8, 0), time(12, 0)),
    ),
    # Cirujanos: consulta temprano, el resto del día es sala de operaciones.
    "quirurgico": (
        (2, time(6, 30), time(11, 30)),
        (3, time(6, 30), time(11, 30)),
        (4, time(6, 30), time(11, 30)),
    ),
    # Emergenciología: cobertura larga de tarde-noche, incluye sábado.
    "guardia": tuple((d, time(14, 0), time(19, 0)) for d in range(1, 7)),
    # Servicios de apoyo (laboratorio, imágenes): bloque corrido.
    "apoyo": tuple((d, time(7, 0), time(15, 0)) for d in range(1, 6)),
}


def _patron_por_medico() -> dict[str, str]:
    """Mapa nombre_normalizado -> clave de patrón horario."""
    mapa: dict[str, str] = {}
    for cfg in _USUARIOS_BASE:
        if cfg["rol"] != RolUsuario.medico:
            continue
        nombre = cfg["nombre"].removeprefix("Dr. ").removeprefix("Dra. ")
        mapa[nombre] = cfg.get("_patron", "completo")
    for cfg in _MEDICOS_SIN_USUARIO:
        nombre = cfg["nombre"].removeprefix("Dr. ").removeprefix("Dra. ")
        mapa[nombre] = cfg.get("_patron", "completo")
    return mapa


def seed_horarios(
    session: Session, medicos: Optional[Iterable[Medico]] = None
) -> int:
    """Configura el horario de atención de cada médico que aún no tenga uno.

    Idempotente: solo crea horarios si el médico aún no tiene ninguno.
    Devuelve el número de horarios nuevos creados.

    Los médicos INACTIVOS también reciben horario. Su franja de atención
    existió mientras estuvieron activos y la pantalla de disponibilidad
    debe poder explicarla; el flag `medicos.activo` es el que gobierna si
    se les puede agendar (validar_disponibilidad rechaza inactivos y
    proxima_disponibilidad devuelve None), no la ausencia de horarios.
    """
    if medicos is None:
        medicos = session.exec(select(Medico)).all()

    admin = session.exec(
        select(Usuario).where(Usuario.email == ADMIN_EMAIL)
    ).first()
    patrones = _patron_por_medico()

    creados = 0
    for m in medicos:
        ya_tiene = session.exec(
            select(Horario).where(Horario.id_medico == m.id)
        ).first()
        if ya_tiene:
            continue
        bloques = _PATRONES_HORARIO[patrones.get(m.nombre, "completo")]
        for dia, hi, hf in bloques:
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
            f"Seed horarios de atención para médico {m.nombre}",
        )

    session.commit()
    logger.info("seed_horarios: %d horarios creados", creados)
    return creados


# ====================================================================
# seed_pacientes
# ====================================================================
_OBJETIVO_PACIENTES = 220

# Sexos usados por el GENERADOR. El modelo admite además 'otro' y
# 'prefiero no decir' (ver SexoPaciente y el CHECK de la tabla), y esas
# opciones siguen disponibles en el formulario para quien edite un
# paciente. Simplemente no se fabrican automáticamente: el nombre de
# pila del catálogo dominicano es binario y un registro con nombre
# "María" y sexo "otro" se lee como dato inventado.
_SEXOS_GENERADOS = (SexoPaciente.masculino.value, SexoPaciente.femenino.value)

# Pirámide poblacional aproximada de la demanda hospitalaria: pocos
# niños, mucho adulto joven y de mediana edad, cola de adultos mayores.
_TRAMOS_EDAD = ((1, 14, 12), (15, 29, 24), (30, 44, 26), (45, 59, 20), (60, 89, 18))


def _fecha_nacimiento(rng: random.Random, hoy: date) -> date:
    """Fecha de nacimiento coherente con un tramo etario ponderado.

    Se calcula restando años a la fecha de hoy y desplazando un número
    aleatorio de días, de modo que la EDAD derivada de la fecha coincide
    exactamente con el tramo elegido (no se guarda edad en BD: se calcula
    siempre a partir de esta fecha, así nunca se desincroniza).
    """
    tramos = [t for t in _TRAMOS_EDAD]
    pesos = [t[2] for t in tramos]
    minimo, maximo, _ = rng.choices(tramos, weights=pesos, k=1)[0]
    edad = rng.randint(minimo, maximo)
    try:
        base = hoy.replace(year=hoy.year - edad)
    except ValueError:  # 29 de febrero en año no bisiesto
        base = hoy.replace(year=hoy.year - edad, day=28)
    return base - timedelta(days=rng.randint(0, 364))


def seed_pacientes(session: Session) -> list[Paciente]:
    """Completa el padrón hasta _OBJETIVO_PACIENTES pacientes.

    Top-up: cuenta lo que ya existe y crea sólo la diferencia, así el
    padrón puede ampliarse subiendo la constante sin tocar ni duplicar
    los pacientes ya registrados (que pueden venir del uso real del
    sistema, no del seed).

    Cada paciente lleva cédula dominicana con dígito verificador válido,
    nombre y apellidos del catálogo local, fecha de nacimiento coherente
    con su tramo etario, teléfono 809/829/849 y dirección de La Vega o
    del Cibao. La fecha de registro se reparte en los últimos ~18 meses
    para que el padrón parezca haber crecido con el tiempo.

    OJO: la tabla `pacientes` NO tiene columna de correo electrónico (se
    eliminó del modelo; ver la nota de scripts/init.sql). El contacto del
    paciente es teléfono + dirección.
    """
    existentes = list(session.exec(select(Paciente)).all())
    faltan = _OBJETIVO_PACIENTES - len(existentes)
    if faltan <= 0:
        logger.info("seed_pacientes: %d ya existen (objetivo %d), omito",
                    len(existentes), _OBJETIVO_PACIENTES)
        return existentes

    rng = random.Random(_SEED + 100)
    admin = session.exec(
        select(Usuario).where(Usuario.email == ADMIN_EMAIL)
    ).first()
    ahora = ahora_local()
    hoy = ahora.date()
    cedulas = {p.cedula for p in existentes}

    creados: list[Paciente] = []
    intentos = 0
    while len(creados) < faltan and intentos < faltan * 8:
        intentos += 1
        cedula = generar_cedula_dominicana(rng)
        # Defensa: si tropezamos con una cédula ya emitida (improbable), reintentar.
        if cedula in cedulas:
            continue
        cedulas.add(cedula)

        sexo = rng.choice(_SEXOS_GENERADOS)
        nombre, apellidos = _nombre_aleatorio(rng, sexo)
        # Registro repartido en ~18 meses; el grueso antes de que empiece
        # la ventana de citas para que ninguna cita preceda a su paciente.
        dias_atras = rng.randint(20, 540)
        registro = ahora - timedelta(
            days=dias_atras, hours=rng.randint(0, 9), minutes=rng.randint(0, 59)
        )

        p = Paciente(
            cedula=cedula,
            nombre=nombre,
            apellidos=apellidos,
            sexo=sexo,
            fecha_nacimiento=_fecha_nacimiento(rng, hoy),
            telefono=_telefono_rd(rng),
            direccion=_direccion_rd(rng) if rng.random() < 0.92 else None,
            fecha_registro=registro,
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
            cuando=p.fecha_registro,
            ip_origen=rng.choice(_IPS_INTRANET),
        )

    session.commit()
    logger.info("seed_pacientes: %d creados, %d total(es)",
                len(creados), len(existentes) + len(creados))
    return list(session.exec(select(Paciente)).all())


# ====================================================================
# seed_citas
# ====================================================================
# Ventana temporal del demo: ~5 meses de historia + ~6 semanas a futuro.
# Cubre de sobra "citas por rango de fechas" en reportes y deja el
# calendario con actividad hacia adelante y hacia atrás.
_HISTORIA_DIAS = 150
_FUTURO_DIAS = 45
_OBJETIVO_CITAS = 2000

# Umbral de convergencia. Generar citas es "best effort": cada intento
# puede caer en un slot ya ocupado, en un día sin horario para ese médico
# o en un paciente que ya tiene cita a esa hora, así que la corrida se
# queda un poco por debajo del objetivo. Al llegar a este umbral se da
# por cumplida la meta; sin él, cada nueva corrida intentaría rellenar el
# hueco residual y el seed dejaría de ser idempotente.
_UMBRAL_CITAS = int(_OBJETIVO_CITAS * 0.95)

# Carga relativa por médico. La lista se recorre en orden y se recicla si
# hay más médicos que entradas. Los valores NO son cantidades absolutas
# —se reescalan para cuadrar con _OBJETIVO_CITAS—; lo que importa es la
# PROPORCIÓN: el médico más ocupado atiende ~10x lo que el menos ocupado.
# Un hospital donde todos los especialistas tienen exactamente la misma
# agenda se ve fabricado a primera vista.
_PERFIL_CARGA: tuple[float, ...] = (
    2.10, 1.75, 1.55, 1.40, 1.25, 1.10, 1.00, 0.90, 0.80,
    0.72, 0.65, 0.58, 0.50, 0.44, 0.38, 0.32, 0.27, 0.22,
)

# Proporción del objetivo reservada a los médicos ya dados de baja. Su
# historial es pequeño y siempre antiguo — dejaron de atender.
_CUOTA_MEDICOS_INACTIVOS = 0.03

# Refuerzo de la agenda inmediata: mínimo de citas por médico activo en
# cada día con horario de la próxima semana. Evita que la agenda del rol
# médico salga vacía en la demostración y, de paso, refleja lo que pasa
# en un hospital real: la semana en curso está llena y el mes que viene
# todavía tiene huecos.
_DIAS_REFUERZO = 8
_MIN_CITAS_DIA_MEDICO = 3


def _dias_con_atencion(desde: date, hasta: date) -> list[date]:
    """Fechas del rango (inclusive) en las que el hospital da consulta.

    Domingo queda fuera: ningún patrón de _PATRONES_HORARIO cubre el día 7.
    """
    dias: list[date] = []
    d = desde
    while d <= hasta:
        if d.isoweekday() != 7:
            dias.append(d)
        d += timedelta(days=1)
    return dias


def _slots_por_medico(
    session: Session, medicos: Iterable[Medico]
) -> dict[int, dict[int, list[time]]]:
    """Precalcula {id_medico: {dia_semana: [slots de 30 min]}}.

    Se hace UNA vez y se consulta en memoria. La versión anterior pedía
    los horarios a la BD por cada intento de cita; con ~2000 citas eso
    eran miles de SELECT innecesarios y el seed tardaba minutos.
    """
    ids = [m.id for m in medicos if m.id is not None]
    mapa: dict[int, dict[int, list[time]]] = {i: {} for i in ids}
    if not ids:
        return mapa

    horarios = session.exec(
        select(Horario).where(
            Horario.activo == True,  # noqa: E712
            Horario.id_medico.in_(ids),
        )
    ).all()
    ancla = date(2000, 1, 1)  # fecha irrelevante: solo se usa la parte horaria
    for h in horarios:
        acumulado = mapa.setdefault(h.id_medico, {}).setdefault(h.dia_semana, [])
        cur = datetime.combine(ancla, h.hora_inicio)
        fin = datetime.combine(ancla, h.hora_fin)
        while cur < fin:
            acumulado.append(cur.time())
            cur += timedelta(minutes=30)
    for por_dia in mapa.values():
        for dia, slots in por_dia.items():
            por_dia[dia] = sorted(set(slots))
    return mapa


def _factor_ocupacion(fecha: date, rng: random.Random) -> float:
    """Multiplicador de actividad del día.

    Modela lo que se ve en una agenda real: el lunes se acumula lo del
    fin de semana, el sábado es media jornada, y siempre hay días
    flojos y días desbordados. Es lo que produce el contraste que el
    calendario necesita para no verse como una cuadrícula uniforme.
    """
    dia = fecha.isoweekday()
    if dia == 6:      # sábado: solo algunos médicos, media jornada
        base = 0.40
    elif dia == 1:    # lunes: pico de la semana
        base = 1.30
    elif dia == 5:    # viernes: baja un poco
        base = 0.90
    else:
        base = 1.0
    return base * rng.choice((0.45, 0.7, 1.0, 1.0, 1.25, 1.55))


def _estado_para(
    fecha: date, hora: time, hoy: date, hora_actual: time, rng: random.Random
) -> EstadoCita:
    """Estado plausible de una cita según su posición respecto de ahora.

    Reglas:
      - Pasado consolidado (más de 3 días atrás): la cita ya se cerró —
        atendida o cancelada. Dejar pendientes viejas es justo lo que
        delata una base de datos abandonada.
      - Últimos 3 días: casi todo cerrado, pero se admite alguna
        pendiente sin registrar (el papeleo va con retraso).
      - Hoy: lo que ya pasó está atendido, lo que viene está pendiente.
      - Futuro: pendiente, salvo las canceladas por el paciente.
    """
    if fecha < hoy - timedelta(days=3):
        return EstadoCita.atendida if rng.random() < 0.89 else EstadoCita.cancelada
    if fecha < hoy:
        r = rng.random()
        if r < 0.78:
            return EstadoCita.atendida
        return EstadoCita.cancelada if r < 0.88 else EstadoCita.pendiente
    if fecha == hoy and hora <= hora_actual:
        r = rng.random()
        if r < 0.80:
            return EstadoCita.atendida
        return EstadoCita.pendiente if r < 0.93 else EstadoCita.cancelada
    # Hoy más tarde, o cualquier fecha futura: sigue en pie salvo el ~6%
    # que el paciente canceló por adelantado.
    return EstadoCita.pendiente if rng.random() < 0.94 else EstadoCita.cancelada


def seed_citas(
    session: Session,
    medicos: Optional[Iterable[Medico]] = None,
    pacientes: Optional[Iterable[Paciente]] = None,
    secretarias: Optional[Iterable[Usuario]] = None,
) -> list[Cita]:
    """Completa la agenda hasta _OBJETIVO_CITAS citas.

    Top-up: cuenta las citas existentes (vengan del seed o del uso real
    del sistema) y genera sólo la diferencia, respetando los slots ya
    ocupados. Alcanzado el objetivo no crea nada — la segunda corrida es
    un no-op, como verifica tests/test_seed.py.

    Cómo se distribuyen:
      - Ventana de _HISTORIA_DIAS hacia atrás y _FUTURO_DIAS hacia
        adelante, sin domingos.
      - Cada día recibe un factor de ocupación aleatorio (_factor_ocupacion)
        y cada médico un peso de carga fijo (_PERFIL_CARGA): así hay días
        desbordados y días flojos, médicos con agenda llena y médicos con
        consulta esporádica.
      - Las citas de un mismo médico en un mismo día salen en slots
        CONSECUTIVOS desde una hora de arranque aleatoria: una agenda real
        se llena en bloque, no salpicada por todo el día.
      - Los estados los decide _estado_para en función de la fecha.

    Invariantes que se respetan (las mismas que valida citas_service):
      - La hora siempre cae dentro de un horario activo del médico
        (los slots se derivan de la tabla `horarios`).
      - No hay dos citas NO canceladas del mismo médico en el mismo
        (fecha, hora) — el set `ocupados_medico` lo impide antes de que
        el índice único parcial tenga que intervenir.
      - Tampoco un mismo paciente aparece en dos consultorios a la misma
        hora (`ocupados_paciente`), que el índice de BD no cubre pero
        sería un absurdo visible en el historial.

    Tras el reparto masivo se ejecuta SIEMPRE un refuerzo de la semana en
    curso (_reforzar_agenda_proxima): garantiza un mínimo de citas por
    médico en los próximos días para que ninguna agenda del rol médico
    aparezca vacía. Es idempotente — solo actúa donde falta el mínimo.
    """
    existentes = list(session.exec(select(Cita)).all())
    faltan = _OBJETIVO_CITAS - len(existentes)
    generacion_masiva = len(existentes) < _UMBRAL_CITAS
    if not generacion_masiva:
        logger.info("seed_citas: %d ya existen (objetivo %d, umbral %d), "
                    "solo refuerzo de agenda próxima",
                    len(existentes), _OBJETIVO_CITAS, _UMBRAL_CITAS)

    if medicos is None:
        medicos = session.exec(select(Medico)).all()
    if pacientes is None:
        pacientes = session.exec(select(Paciente)).all()
    if secretarias is None:
        secretarias = session.exec(
            select(Usuario).where(Usuario.rol == RolUsuario.secretaria)
        ).all()

    medicos = list(medicos)
    activos = [m for m in medicos if m.activo]
    inactivos = [m for m in medicos if not m.activo]
    pacientes = list(pacientes)
    secretarias = list(secretarias)
    if not activos or not pacientes or not secretarias:
        logger.warning("seed_citas: faltan médicos activos / pacientes / secretarias")
        return existentes

    rng = random.Random(_SEED + 200)
    ahora = ahora_local()
    hoy = ahora.date()
    hora_actual = ahora.time()

    slots_medico = _slots_por_medico(session, medicos)
    ocupados_medico = {
        (c.id_medico, c.fecha, c.hora)
        for c in existentes
        if c.estado != EstadoCita.cancelada
    }
    ocupados_paciente = {
        (c.id_paciente, c.fecha, c.hora)
        for c in existentes
        if c.estado != EstadoCita.cancelada
    }
    # Conteo por (médico, día) que SÍ incluye las canceladas. El refuerzo
    # de agenda lo usa para medir cuánto trabajo tiene ya ese médico ese
    # día: una cita cancelada libera el slot (no entra en `ocupados_*`)
    # pero sigue apareciendo en su agenda, así que contarla evita que el
    # refuerzo la ignore y agregue citas de más en cada corrida.
    citas_por_dia: dict[tuple[int, date], int] = {}
    for c in existentes:
        clave = (c.id_medico, c.fecha)
        citas_por_dia[clave] = citas_por_dia.get(clave, 0) + 1

    # Cartera de pacientes habituales por médico: el 72% de las citas de
    # un médico sale de su propia cartera. Sin esto, cada paciente vería
    # a un especialista distinto cada vez y el historial clínico por
    # médico quedaría con una sola consulta por paciente — inútil para
    # demostrar la pantalla de historial.
    tamano_cartera = max(12, len(pacientes) // 4)
    cartera: dict[int, list[Paciente]] = {
        m.id: rng.sample(pacientes, min(tamano_cartera, len(pacientes)))
        for m in medicos
    }

    # Las secretarias no reparten el trabajo por igual: la de más
    # antigüedad agenda bastante más. Hace que el reporte "secretaria con
    # más citas creadas" tenga un ganador claro y no un empate técnico.
    pesos_secretarias = [
        max(1.0, 4.0 - i * 0.6) for i in range(len(secretarias))
    ]

    def elegir_paciente(
        id_medico: int, fecha: date, hora: time, cita_dt: datetime
    ) -> Optional[Paciente]:
        """Paciente libre a esa hora y YA registrado cuando ocurre la cita.

        La segunda condición no es cosmética: un paciente no puede tener
        una cita anterior a su propio registro en el hospital. Sin este
        filtro, los pacientes registrados hace poco acababan con historial
        clínico de hace cinco meses.
        """
        for _ in range(8):
            propios = cartera.get(id_medico) or pacientes
            p = rng.choice(propios) if rng.random() < 0.72 else rng.choice(pacientes)
            if (p.id, fecha, hora) in ocupados_paciente:
                continue
            if _como_aware(p.fecha_registro, ahora) >= cita_dt - timedelta(hours=3):
                continue
            return p
        return None

    creadas: list[Cita] = []

    def crear_cita(m: Medico, d: date, hora: time) -> bool:
        """Materializa una cita para (médico, día, hora). False si no se pudo.

        Único punto donde se construye una fila de `citas` en este seeder:
        tanto el reparto masivo como el refuerzo de la semana pasan por
        aquí, así los invariantes (slot libre, paciente libre, fecha de
        agendamiento coherente) se aplican una sola vez.
        """
        cita_dt = _aware(d, hora)
        paciente = elegir_paciente(m.id, d, hora, cita_dt)
        if paciente is None:
            return False
        estado = _estado_para(d, hora, hoy, hora_actual, rng)

        # Fecha de agendamiento: entre 1 y 25 días antes de la atención,
        # nunca en el futuro y nunca antes de que el paciente estuviera
        # registrado. elegir_paciente ya garantiza que el registro del
        # paciente precede a la cita, así que ambos topes son compatibles.
        registro = cita_dt - timedelta(
            days=rng.randint(1, 25), hours=rng.randint(0, 6)
        )
        if registro > ahora:
            registro = ahora - timedelta(hours=rng.randint(1, 72))
        piso = _como_aware(paciente.fecha_registro, ahora) + timedelta(hours=1)
        if registro < piso:
            registro = piso

        sec = rng.choices(secretarias, weights=pesos_secretarias, k=1)[0]
        cita = Cita(
            id_paciente=paciente.id,
            id_medico=m.id,
            fecha=d,
            hora=hora,
            estado=estado,
            motivo=(
                rng.choice(_MOTIVOS_CITA_GENERICOS)
                if rng.random() < 0.92
                else None
            ),
            id_secretaria=sec.id,
            fecha_registro=registro,
        )
        session.add(cita)
        creadas.append(cita)
        citas_por_dia[(m.id, d)] = citas_por_dia.get((m.id, d), 0) + 1
        if estado != EstadoCita.cancelada:
            ocupados_medico.add((m.id, d, hora))
            ocupados_paciente.add((paciente.id, d, hora))
        return True

    def poblar(
        medicos_objetivo: list[Medico], dias: list[date], cupo: int
    ) -> int:
        """Reparte `cupo` citas entre `medicos_objetivo` a lo largo de `dias`.

        Devuelve cuántas creó realmente — casi siempre menos que `cupo`,
        porque hay slots ya ocupados y pacientes no disponibles. El
        llamador repite la pasada con el remanente hasta converger.
        """
        if not medicos_objetivo or not dias or cupo <= 0:
            return 0

        pesos = {
            m.id: _PERFIL_CARGA[i % len(_PERFIL_CARGA)]
            for i, m in enumerate(medicos_objetivo)
        }
        factores = {d: _factor_ocupacion(d, rng) for d in dias}
        # Escala global para que la suma esperada cuadre con el cupo.
        esperado = sum(factores[d] for d in dias) * sum(pesos.values())
        if esperado <= 0:
            return 0
        escala = cupo / esperado

        creadas_local = 0
        for d in dias:
            if creadas_local >= cupo:
                break
            dia_semana = d.isoweekday()
            for m in medicos_objetivo:
                if creadas_local >= cupo:
                    break
                disponibles = [
                    s
                    for s in slots_medico.get(m.id, {}).get(dia_semana, ())
                    if (m.id, d, s) not in ocupados_medico
                ]
                if not disponibles:
                    continue

                esperados = pesos[m.id] * factores[d] * escala
                n = int(esperados)
                if rng.random() < esperados - n:
                    n += 1
                n = min(n, len(disponibles), 12)
                if n <= 0:
                    continue

                # Bloque consecutivo desde un arranque aleatorio (con
                # vuelta al principio si el bloque se pasa del final).
                inicio = rng.randrange(len(disponibles))
                elegidos = disponibles[inicio:inicio + n]
                if len(elegidos) < n:
                    elegidos = elegidos + disponibles[: n - len(elegidos)]

                for hora in elegidos:
                    if crear_cita(m, d, hora):
                        creadas_local += 1
                    if creadas_local >= cupo:
                        break
        return creadas_local

    def poblar_hasta(
        medicos_objetivo: list[Medico], dias: list[date], cupo: int
    ) -> None:
        """Repite `poblar` con el remanente hasta cubrir el cupo o estancarse."""
        restante = cupo
        for _ in range(8):
            if restante <= 0:
                break
            hechas = poblar(medicos_objetivo, dias, restante)
            if hechas == 0:
                break
            restante -= hechas

    def reforzar_agenda_proxima() -> int:
        """Asegura un mínimo de citas por médico en los próximos días.

        POR QUÉ: el reparto masivo es estadístico y un médico puede quedar
        sin ninguna cita en el día en curso — sobre todo en sábado, donde
        solo una parte de la plantilla atiende. Para una demostración en
        vivo eso significa abrir la agenda del rol médico y encontrarla
        vacía, que es justo lo que no puede pasar.

        Solo rellena el DÉFICIT (médicos por debajo del mínimo en un día
        en que sí tienen horario), así que repetirlo no acumula citas.
        """
        reforzadas = 0
        for d in _dias_con_atencion(hoy, hoy + timedelta(days=_DIAS_REFUERZO)):
            dia_semana = d.isoweekday()
            for m in activos:
                slots = slots_medico.get(m.id, {}).get(dia_semana, ())
                if not slots:
                    continue
                # En el día en curso también se rellenan las horas ya
                # pasadas: la agenda del médico muestra la jornada
                # completa, y _estado_para las marca como atendidas. Si se
                # excluyeran, un médico cuyo turno terminó a mediodía
                # abriría su agenda vacía el resto del día.
                libres = [s for s in slots if (m.id, d, s) not in ocupados_medico]
                ya_tiene = citas_por_dia.get((m.id, d), 0)
                faltantes = min(_MIN_CITAS_DIA_MEDICO - ya_tiene, len(libres))
                for hora in libres[:max(0, faltantes)]:
                    if crear_cita(m, d, hora):
                        reforzadas += 1
        return reforzadas

    cupo_inactivos = int(faltan * _CUOTA_MEDICOS_INACTIVOS) if inactivos else 0
    dias_completos = _dias_con_atencion(
        hoy - timedelta(days=_HISTORIA_DIAS), hoy + timedelta(days=_FUTURO_DIAS)
    )
    # Los médicos dados de baja solo tienen historial antiguo: dejaron de
    # atender bastante antes de que se les desactivara la cuenta.
    dias_antiguos = _dias_con_atencion(
        hoy - timedelta(days=_HISTORIA_DIAS), hoy - timedelta(days=60)
    )

    if generacion_masiva:
        poblar_hasta(activos, dias_completos, faltan - cupo_inactivos)
        poblar_hasta(inactivos, dias_antiguos, cupo_inactivos)
    reforzadas = reforzar_agenda_proxima()

    if not creadas:
        logger.info("seed_citas: nada que crear")
        return existentes

    session.flush()

    # Auditoría — la secretaria de la cita es el actor natural.
    # Además de la creación se registran los eventos posteriores que la
    # cita habría acumulado: cancelaciones (DELETE, igual que hace el
    # endpoint) y reprogramaciones (UPDATE). Sin ellos la bitácora sería
    # una lista monótona de CREATE.
    sec_actor_por_id = {s.id: s for s in secretarias}
    for c in creadas:
        actor = sec_actor_por_id.get(c.id_secretaria, secretarias[0])
        ip = rng.choice(_IPS_INTRANET)
        _audit(
            session,
            actor,
            AccionAuditoria.CREATE,
            "citas",
            c.id,
            f"Cita medico={c.id_medico} {c.fecha} {c.hora}",
            cuando=c.fecha_registro,
            ip_origen=ip,
        )
        if c.estado == EstadoCita.cancelada:
            _audit(
                session,
                actor,
                AccionAuditoria.DELETE,
                "citas",
                c.id,
                "Cancelación de cita",
                cuando=c.fecha_registro + timedelta(days=rng.randint(1, 4)),
                ip_origen=ip,
            )
        elif rng.random() < 0.06:
            _audit(
                session,
                actor,
                AccionAuditoria.UPDATE,
                "citas",
                c.id,
                "Update ['fecha', 'hora']",
                cuando=c.fecha_registro + timedelta(hours=rng.randint(4, 48)),
                ip_origen=ip,
            )

    session.commit()
    logger.info("seed_citas: %d creadas (%d de refuerzo), %d total(es)",
                len(creadas), reforzadas, len(existentes) + len(creadas))
    return list(session.exec(select(Cita)).all())


# ====================================================================
# seed_consultas
# ====================================================================
def seed_consultas(
    session: Session, citas: Optional[Iterable[Cita]] = None
) -> list[Consulta]:
    """Registra una consulta por cada cita atendida que aún no la tenga.

    Relación 1-a-1 con la cita (UNIQUE en consultas.id_cita): en el flujo
    real es el registro de la consulta lo que marca la cita como atendida,
    así que una cita atendida SIN consulta sería un hueco en el historial
    clínico y dejaría vacío el PDF de historial médico.

    El contenido sale de _PLANTILLAS_POR_ESPECIALIDAD según la
    especialidad del médico que atendió, con comorbilidad añadida en
    ~35% de los casos. `observaciones` queda en None a propósito: es el
    campo legacy pre-Mejora 3.2 y los registros nuevos usan los campos
    estructurados.
    """
    if citas is None:
        citas = session.exec(
            select(Cita).where(Cita.estado == EstadoCita.atendida)
        ).all()
    atendidas = [c for c in citas if c.estado == EstadoCita.atendida]

    ya_registradas = {
        c.id_cita for c in session.exec(select(Consulta)).all()
    }
    pendientes = [c for c in atendidas if c.id not in ya_registradas]
    if not pendientes:
        logger.info("seed_consultas: todas las citas atendidas ya tienen consulta")
        return list(session.exec(select(Consulta)).all())

    rng = random.Random(_SEED + 300)
    medicos_cache = {m.id: m for m in session.exec(select(Medico)).all()}
    usuarios_por_medico = {
        m.id: session.get(Usuario, m.id_usuario)
        for m in medicos_cache.values()
        if m.id_usuario
    }

    creadas: list[Consulta] = []
    for cita in pendientes:
        medico = medicos_cache.get(cita.id_medico)
        especialidad = medico.especialidad if medico else None

        plantillas = _PLANTILLAS_POR_ESPECIALIDAD.get(especialidad or "", [])
        plantilla = rng.choice(plantillas) if plantillas else _PLANTILLA_GENERICA

        # La consulta se registra al terminar la atención: entre 20 y 90
        # minutos después de la hora agendada.
        registro = _aware(cita.fecha, cita.hora) + timedelta(
            minutes=rng.randint(20, 90)
        )

        consulta = Consulta(
            id_cita=cita.id,
            motivo_consulta=plantilla["motivo_consulta"],
            examen_fisico=plantilla["examen_fisico"],
            condicion_principal=plantilla["condicion_principal"],
            condiciones_secundarias=(
                rng.choice(_CONDICIONES_SECUNDARIAS) if rng.random() < 0.35 else None
            ),
            tratamiento=plantilla["tratamiento"],
            fecha_registro=registro,
        )
        session.add(consulta)
        creadas.append(consulta)

    session.flush()

    # Auditoría — el médico de la cita es el actor que registra la consulta.
    citas_por_id = {c.id: c for c in pendientes}
    for c in creadas:
        cita = citas_por_id[c.id_cita]
        medico = medicos_cache.get(cita.id_medico)
        actor = usuarios_por_medico.get(medico.id) if medico else None
        _audit(
            session,
            actor,
            AccionAuditoria.CREATE,
            "consultas",
            c.id,
            f"Consulta cita={c.id_cita}",
            cuando=c.fecha_registro,
            ip_origen=rng.choice(_IPS_INTRANET),
        )

    session.commit()
    logger.info("seed_consultas: %d creadas", len(creadas))
    return list(session.exec(select(Consulta)).all())


# ====================================================================
# seed_accesos — bitácora de inicios de sesión
# ====================================================================
_OBJETIVO_ACCESOS = 620


def seed_accesos(session: Session) -> int:
    """Genera registros de auditoría LOGIN repartidos por la historia.

    Por qué existe: la pantalla de auditoría permite filtrar por acción y,
    sin estos registros, el filtro LOGIN aparece vacío y el resto de la
    bitácora se ve como una carga masiva de un solo día. Un sistema que
    lleva meses operando tiene, sobre todo, gente entrando y saliendo.

    El formato del detalle es idéntico al que escribe el endpoint real de
    login (app/api/v1/endpoints/auth.py), para que las filas del seed y
    las de uso real sean indistinguibles en pantalla.

    Idempotente por conteo: si ya hay _OBJETIVO_ACCESOS registros LOGIN,
    no crea ninguno más.
    """
    existentes = len(
        session.exec(
            select(Auditoria).where(Auditoria.accion == AccionAuditoria.LOGIN)
        ).all()
    )
    faltan = _OBJETIVO_ACCESOS - existentes
    if faltan <= 0:
        logger.info("seed_accesos: %d registros LOGIN ya existen, omito", existentes)
        return 0

    usuarios = [u for u in session.exec(select(Usuario)).all() if u.activo]
    if not usuarios:
        logger.warning("seed_accesos: no hay usuarios activos")
        return 0

    # La secretaria entra varias veces al día; el médico una o dos; el
    # admin solo cuando hace falta.
    peso_rol = {
        RolUsuario.secretaria: 5.0,
        RolUsuario.medico: 2.0,
        RolUsuario.admin: 1.0,
    }
    pesos = [peso_rol.get(u.rol, 1.0) for u in usuarios]

    rng = random.Random(_SEED + 600)
    ahora = ahora_local()
    hoy = ahora.date()
    dias = _dias_con_atencion(hoy - timedelta(days=_HISTORIA_DIAS), hoy)
    por_dia = faltan / len(dias)

    creados = 0
    for d in dias:
        if creados >= faltan:
            break
        n = int(por_dia)
        if rng.random() < por_dia - n:
            n += 1
        n = max(0, n + rng.choice((-1, 0, 0, 1)))
        for _ in range(n):
            if creados >= faltan:
                break
            u = rng.choices(usuarios, weights=pesos, k=1)[0]
            momento = _aware(
                d, time(rng.randint(6, 16), rng.choice((0, 5, 12, 18, 25, 33, 41, 47, 55)))
            )
            if momento > ahora:
                continue
            _audit(
                session,
                u,
                AccionAuditoria.LOGIN,
                "usuarios",
                u.id,
                f"Login exitoso ({u.email})",
                cuando=momento,
                ip_origen=rng.choice(_IPS_INTRANET),
            )
            creados += 1

    session.commit()
    logger.info("seed_accesos: %d registros LOGIN creados", creados)
    return creados


# ====================================================================
# normalizar_historico
# ====================================================================
def normalizar_historico(session: Session) -> dict[str, int]:
    """Deja coherente el histórico acumulado de corridas anteriores.

    NO borra ni reescribe información sustantiva: sólo cierra lo que el
    paso del tiempo dejó inconsistente.

    1. Citas PENDIENTES con fecha vencida (más de 3 días atrás). En el
       flujo real toda cita termina atendida o cancelada; una pendiente
       de hace dos meses significa que nadie tocó el sistema desde
       entonces. Se cierran como atendida (86%) o cancelada, y la cita
       atendida recibe su consulta en el paso siguiente de seed_all.
       El margen de 3 días es deliberado: las citas recién pasadas
       siguen pendientes de cerrar y eso SÍ es realista.

    2. Pacientes con sexo distinto de masculino/femenino generados por
       corridas anteriores del seed. El valor se deduce del nombre de
       pila. Las cuatro opciones siguen vigentes en el modelo y en el
       formulario (ver _SEXOS_GENERADOS); lo que se corrige es que el
       generador antiguo las repartía al azar y producía registros con
       nombre y sexo incongruentes.

    3. Pacientes cuya fecha de registro es POSTERIOR a su primera cita.
       Pasa con las filas que corridas viejas estamparon con `now()`: el
       paciente aparece registrado en mayo con historial clínico desde
       marzo. Se retrocede el registro a un par de días antes de la
       primera cita, que es el orden real de los hechos (nadie recibe
       consulta antes de estar registrado).

    4. Registros de auditoría fechados en el futuro. La pantalla ordena
       por fecha_hora DESC, así que una fila adelantada se queda fija en
       el tope de la bitácora.

    Idempotente: en una segunda corrida no queda nada por normalizar.
    """
    rng = random.Random(_SEED + 500)
    ahora = ahora_local()
    hoy = ahora.date()
    limite = hoy - timedelta(days=3)

    admin = session.exec(
        select(Usuario).where(Usuario.email == ADMIN_EMAIL)
    ).first()

    vencidas = session.exec(
        select(Cita).where(
            Cita.fecha < limite,
            Cita.estado == EstadoCita.pendiente,
        )
    ).all()

    atendidas = canceladas = 0
    for c in vencidas:
        cierre = _aware(c.fecha, c.hora) + timedelta(minutes=rng.randint(25, 120))
        if rng.random() < 0.86:
            c.estado = EstadoCita.atendida
            atendidas += 1
            accion, detalle = AccionAuditoria.UPDATE, "Update ['estado'] → atendida"
        else:
            c.estado = EstadoCita.cancelada
            canceladas += 1
            accion, detalle = AccionAuditoria.DELETE, "Cancelación de cita"
        session.add(c)
        _audit(
            session, admin, accion, "citas", c.id, detalle,
            cuando=cierre, ip_origen=rng.choice(_IPS_INTRANET),
        )

    # Sexo incongruente heredado de generaciones anteriores del seed.
    nombres_m = set(_NOMBRES_M)
    nombres_f = set(_NOMBRES_F)
    ajustados = 0
    for p in session.exec(select(Paciente)).all():
        if p.sexo in _SEXOS_GENERADOS:
            continue
        if p.nombre in nombres_m:
            p.sexo = SexoPaciente.masculino.value
        elif p.nombre in nombres_f:
            p.sexo = SexoPaciente.femenino.value
        else:
            continue
        session.add(p)
        ajustados += 1
        marca = _como_aware(p.fecha_registro, ahora)
        _audit(
            session, admin, AccionAuditoria.UPDATE, "pacientes", p.id,
            "Update ['sexo']",
            cuando=min(marca + timedelta(days=1), ahora),
            ip_origen=rng.choice(_IPS_INTRANET),
        )

    # Registro del paciente anterior a su primera cita.
    primera_cita: dict[int, datetime] = {}
    for c in session.exec(select(Cita)).all():
        marca = min(
            _aware(c.fecha, c.hora), _como_aware(c.fecha_registro, ahora)
        )
        actual = primera_cita.get(c.id_paciente)
        if actual is None or marca < actual:
            primera_cita[c.id_paciente] = marca

    retrocedidos = 0
    for p in session.exec(select(Paciente)).all():
        inicio = primera_cita.get(p.id)
        if inicio is None:
            continue
        if _como_aware(p.fecha_registro, ahora) <= inicio:
            continue
        p.fecha_registro = inicio - timedelta(days=rng.randint(2, 20))
        session.add(p)
        retrocedidos += 1

    # Bitácora con entradas adelantadas (artefacto de corridas previas).
    adelantadas = 0
    for a in session.exec(select(Auditoria)).all():
        if _como_aware(a.fecha_hora, ahora) > ahora:
            a.fecha_hora = ahora - timedelta(minutes=rng.randint(5, 600))
            session.add(a)
            adelantadas += 1

    session.commit()
    resumen = {
        "citas_cerradas_atendidas": atendidas,
        "citas_cerradas_canceladas": canceladas,
        "pacientes_sexo_ajustado": ajustados,
        "pacientes_registro_retrocedido": retrocedidos,
        "auditoria_fechas_corregidas": adelantadas,
    }
    logger.info("normalizar_historico: %s", resumen)
    return resumen


# ====================================================================
# Orquestador
# ====================================================================
def seed_all(session: Session) -> dict:
    """Ejecuta todos los seeders en orden. Devuelve el estado FINAL de la BD.

    El orden importa:
      especialidades → usuarios → médicos → horarios → pacientes → citas
      → normalización → consultas → accesos

    `normalizar_historico` va DESPUÉS de las citas y ANTES de las
    consultas: al cerrar citas vencidas produce nuevas citas atendidas
    que seed_consultas debe documentar en el mismo paso.

    El resumen devuelve TOTALES (no altas nuevas) a propósito: así dos
    corridas seguidas devuelven exactamente el mismo diccionario, que es
    la definición operativa de idempotencia que verifican los tests.
    """
    seed_especialidades(session)
    usuarios = seed_usuarios(session)
    medicos = seed_medicos(session, usuarios)
    seed_horarios(session, medicos)
    pacientes = seed_pacientes(session)
    secretarias = [u for u in usuarios.values() if u.rol == RolUsuario.secretaria]
    citas = seed_citas(session, medicos, pacientes, secretarias)
    normalizar_historico(session)
    seed_consultas(session)
    seed_accesos(session)

    def _total(modelo) -> int:
        return len(session.exec(select(modelo)).all())

    resumen = {
        "especialidades": _total(Especialidad),
        "usuarios": _total(Usuario),
        "medicos": _total(Medico),
        "horarios": _total(Horario),
        "pacientes": _total(Paciente),
        "citas": _total(Cita),
        "consultas": _total(Consulta),
        "auditoria": _total(Auditoria),
    }
    logger.info("seed_all: %s", resumen)
    return resumen


# ====================================================================
# Reset (cuidado: destructivo). Usado por la CLI con --reset.
# ====================================================================
def reset_datos(session: Session) -> None:
    """Borra todas las tablas en orden compatible con las FKs.

    No toca el esquema; solo trunca los datos. Útil en dev para volver
    a un estado limpio antes de re-sembrar.

    CUIDADO: ESTO BORRA TODOS LOS DATOS. La CLI lo expone con flag
    --reset y pide confirmación explícita. Llamarlo desde código sin
    intención = adiós a todo el histórico clínico. No invocar desde
    endpoints, jobs ni middleware bajo ninguna circunstancia.

    OJO: `especialidades` NO se vacía — es catálogo, no dato operativo,
    y sin él fallan las validaciones de alta de médicos.
    """
    # Orden inverso al de creación para respetar FKs.
    for model in (Consulta, Cita, Horario, Medico, Paciente, Auditoria, Usuario):
        for row in session.exec(select(model)).all():
            session.delete(row)
    session.commit()
    logger.info("reset_datos: todas las tablas vaciadas")
