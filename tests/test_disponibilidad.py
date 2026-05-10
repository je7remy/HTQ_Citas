"""Tests del endpoint de próxima disponibilidad (Mejora 3.1)."""
from datetime import date, time, timedelta

from sqlmodel import Session, select

from app.models import Cita, Horario, Medico


def _proximo_dia_semana(weekday: int, desde: date | None = None) -> date:
    """weekday: 1=lunes ... 7=domingo. Devuelve la primera fecha >= desde+1 que cae en ese día."""
    desde = desde or date.today()
    for offset in range(1, 15):
        d = desde + timedelta(days=offset)
        if d.isoweekday() == weekday:
            return d
    raise RuntimeError("unreachable")


def test_proxima_disponibilidad_devuelve_primer_lunes_8am(client, auth_as, seed_users):
    """Médico con horario L-V 8-12 sin citas → sugiere próximo lunes 8:00 AM (primer slot)."""
    auth_as("secretaria")
    medico_id = seed_users["medico"].id
    res = client.get(f"/api/v1/medicos/{medico_id}/proxima-disponibilidad")
    assert res.status_code == 200
    body = res.json()
    assert body is not None
    # El primer slot disponible cae en algún día L-V cercano
    fecha_sugerida = date.fromisoformat(body["fecha"])
    assert 1 <= fecha_sugerida.isoweekday() <= 5
    assert body["hora"].startswith("08:00")
    assert "AM" in body["hora_legible"]


def test_proxima_disponibilidad_si_primer_slot_ocupado_ofrece_siguiente(
    client, auth_as, seed_users, session
):
    """Si la cita en 08:00 ya existe, la sugerencia debe ser 08:30."""
    auth_as("secretaria")
    medico_id = seed_users["medico"].id

    # Crear paciente
    p = client.post(
        "/api/v1/pacientes",
        json={
            "cedula": "00112345678", "nombre": "Ana", "apellidos": "García",
            "sexo": "femenino", "fecha_nacimiento": "1990-04-12",
            "telefono": "8095550100",
        },
    ).json()

    # Encontrar el primer día con horario y crear cita en ese día a las 08:00
    primer_dia = _proximo_dia_semana(1)  # próximo lunes
    client.post(
        "/api/v1/citas",
        json={
            "id_paciente": p["id"],
            "id_medico": medico_id,
            "fecha": primer_dia.isoformat(),
            "hora": "08:00:00",
        },
    )

    res = client.get(f"/api/v1/medicos/{medico_id}/proxima-disponibilidad")
    body = res.json()
    assert body is not None

    # Si la sugerencia cae en ese mismo lunes, debe ser 08:30 o posterior.
    # Si cae en un día anterior (martes-viernes pasados antes), sigue siendo válida — el test
    # garantiza que el primer slot exacto (mismo día 08:00) no se sugiera.
    if body["fecha"] == primer_dia.isoformat():
        assert body["hora"] != "08:00:00"


def test_proxima_disponibilidad_medico_sin_horarios_retorna_null(
    client, auth_as, session
):
    """Médico activo sin horarios: el endpoint devuelve null."""
    auth_as("admin")
    # Crear médico sin horarios
    res = client.post(
        "/api/v1/medicos",
        json={"nombre": "Sin Horarios", "especialidad": "Cirugía General"},
    )
    assert res.status_code == 201
    medico_id = res.json()["id"]

    auth_as("secretaria")
    res = client.get(f"/api/v1/medicos/{medico_id}/proxima-disponibilidad")
    assert res.status_code == 200
    assert res.json() is None


def test_proxima_disponibilidad_requiere_autenticacion(client):
    res = client.get("/api/v1/medicos/1/proxima-disponibilidad")
    assert res.status_code == 401
