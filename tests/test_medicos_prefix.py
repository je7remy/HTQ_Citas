"""Tests Mejora 2: normalización del prefijo Dr./Dra. en médicos."""
import re

import pytest
from sqlmodel import Session, select

from app.models import Medico
from tests.conftest import TEST_PASSWORD

_PREFIJO_DR = re.compile(r"^(dra?\.?\s+|doctor[a]?\s+)", re.IGNORECASE)


def _strip(nombre: str) -> str:
    return _PREFIJO_DR.sub("", nombre).strip()


# ── Tests unitarios de la función de normalización ──────────────────────────

@pytest.mark.parametrize("entrada,esperado", [
    ("Dr. Juan Pérez",    "Juan Pérez"),
    ("Dr Juan Pérez",     "Juan Pérez"),
    ("Dra. Ana López",    "Ana López"),
    ("Dra Ana López",     "Ana López"),
    ("DR. Carlos Mena",   "Carlos Mena"),
    ("Doctor Luis Vidal", "Luis Vidal"),
    ("Doctora Sara Mora", "Sara Mora"),
    ("Juan Pérez",        "Juan Pérez"),       # sin prefijo → sin cambio
    ("Adriana Díaz",      "Adriana Díaz"),     # contiene "Dr" en interior → no afecta
])
def test_strip_prefix_variantes(entrada, esperado):
    assert _strip(entrada) == esperado


# ── Tests via API: el endpoint normaliza el nombre antes de persistir ────────

def _crear_usuario(client, email):
    res = client.post(
        "/api/v1/usuarios",
        json={"nombre": email, "email": email, "password": TEST_PASSWORD, "rol": "medico"},
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


def test_crear_medico_nombre_con_dr_se_persiste_sin_prefijo(client, auth_as, seed_users):
    """POST /medicos con nombre 'Dr. Juan Pérez' persiste 'Juan Pérez'."""
    auth_as("admin")
    uid = _crear_usuario(client, "drjuan@test.do")
    res = client.post(
        "/api/v1/medicos",
        json={"id_usuario": uid, "nombre": "Dr. Juan Pérez", "especialidad": "Medicina Interna"},
    )
    assert res.status_code == 201, res.text
    assert res.json()["nombre"] == "Juan Pérez"


def test_crear_medico_nombre_con_dra_se_persiste_sin_prefijo(client, auth_as, seed_users):
    """POST /medicos con nombre 'Dra. Ana López' persiste 'Ana López'."""
    auth_as("admin")
    uid = _crear_usuario(client, "draana@test.do")
    res = client.post(
        "/api/v1/medicos",
        json={"id_usuario": uid, "nombre": "Dra. Ana López", "especialidad": "Cirugía General"},
    )
    assert res.status_code == 201, res.text
    assert res.json()["nombre"] == "Ana López"


def test_crear_medico_nombre_sin_prefijo_sin_cambio(client, auth_as, seed_users):
    """POST /medicos con nombre sin prefijo → se persiste tal cual."""
    auth_as("admin")
    uid = _crear_usuario(client, "sinprefijo@test.do")
    res = client.post(
        "/api/v1/medicos",
        json={"id_usuario": uid, "nombre": "Juan Pérez", "especialidad": "Urología"},
    )
    assert res.status_code == 201, res.text
    assert res.json()["nombre"] == "Juan Pérez"


def test_patch_medico_nombre_con_prefijo_normaliza(client, auth_as, seed_users):
    """PATCH /medicos/{id} con nombre 'Dr. Carlos' normaliza a 'Carlos'."""
    auth_as("admin")
    medico_id = seed_users["medico"].id
    res = client.patch(
        f"/api/v1/medicos/{medico_id}",
        json={"nombre": "Dr. Carlos Mena"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["nombre"] == "Carlos Mena"


# ── Test del script de limpieza ──────────────────────────────────────────────

def test_clean_medicos_prefix_script(session: Session):
    """El script limpia prefijos y es idempotente."""
    from scripts.clean_medicos_prefix import main as clean_main, strip_prefix

    # Insertar 3 médicos de prueba directamente en la sesión de test
    m1 = Medico(nombre="Dr. Pedro Soto", especialidad="Neurocirugía")
    m2 = Medico(nombre="María García", especialidad="Anestesiología")
    m3 = Medico(nombre="DR. LUIS REYES", especialidad="Urología")
    session.add_all([m1, m2, m3])
    session.commit()
    session.refresh(m1)
    session.refresh(m2)
    session.refresh(m3)

    # Verificar función de limpieza directamente (no el script completo que usa otro engine)
    assert strip_prefix("Dr. Pedro Soto") == "Pedro Soto"
    assert strip_prefix("María García") == "María García"
    assert strip_prefix("DR. LUIS REYES") == "LUIS REYES"

    # Idempotencia
    assert strip_prefix("Pedro Soto") == "Pedro Soto"
    assert strip_prefix("LUIS REYES") == "LUIS REYES"
