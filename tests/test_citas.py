"""Tests del módulo de citas — incluye E-005 y E-006.

Para tener fechas que caigan en lunes/sábado de forma determinista,
calculamos dinámicamente desde hoy.
"""
from datetime import date, timedelta


def _proximo_dia_semana(target_iso: int) -> date:
    """Devuelve la próxima fecha (a partir de mañana) cuyo isoweekday == target_iso."""
    hoy = date.today()
    for offset in range(1, 15):
        d = hoy + timedelta(days=offset)
        if d.isoweekday() == target_iso:
            return d
    raise RuntimeError("unreachable")


def _crear_paciente(client) -> int:
    res = client.post(
        "/api/v1/pacientes",
        json={
            "cedula": "00112345678",
            "nombre": "Ana",
            "apellidos": "García",
            "telefono": "8095550100",
        },
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


def test_crear_cita_ok(client, auth_as, seed_users):
    auth_as("secretaria")
    paciente_id = _crear_paciente(client)
    medico_id = seed_users["medico"].id

    proximo_lunes = _proximo_dia_semana(1)
    res = client.post(
        "/api/v1/citas",
        json={
            "id_paciente": paciente_id,
            "id_medico": medico_id,
            "fecha": proximo_lunes.isoformat(),
            "hora": "09:00:00",
            "motivo": "Consulta de rutina",
        },
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["estado"] == "pendiente"
    assert body["id_secretaria"] == seed_users["secretaria"].id


def test_e005_horario_ocupado(client, auth_as, seed_users):
    """No se permiten dos citas en el mismo (medico, fecha, hora)."""
    auth_as("secretaria")
    paciente_id = _crear_paciente(client)
    medico_id = seed_users["medico"].id
    fecha = _proximo_dia_semana(1).isoformat()

    primera = client.post(
        "/api/v1/citas",
        json={
            "id_paciente": paciente_id,
            "id_medico": medico_id,
            "fecha": fecha,
            "hora": "10:00:00",
        },
    )
    assert primera.status_code == 201

    segunda = client.post(
        "/api/v1/citas",
        json={
            "id_paciente": paciente_id,
            "id_medico": medico_id,
            "fecha": fecha,
            "hora": "10:00:00",
        },
    )
    assert segunda.status_code == 409
    assert "E-005" in segunda.json()["detail"]


def test_e006_fuera_de_horario(client, auth_as, seed_users):
    """Médico atiende L-V 8-12. Una cita a las 14:00 debe rechazarse."""
    auth_as("secretaria")
    paciente_id = _crear_paciente(client)
    medico_id = seed_users["medico"].id

    res = client.post(
        "/api/v1/citas",
        json={
            "id_paciente": paciente_id,
            "id_medico": medico_id,
            "fecha": _proximo_dia_semana(1).isoformat(),
            "hora": "14:00:00",
        },
    )
    assert res.status_code == 409
    assert "E-006" in res.json()["detail"]


def test_e006_dia_no_atendido(client, auth_as, seed_users):
    """Sábado (isoweekday=6) no está en el horario L-V."""
    auth_as("secretaria")
    paciente_id = _crear_paciente(client)
    medico_id = seed_users["medico"].id

    res = client.post(
        "/api/v1/citas",
        json={
            "id_paciente": paciente_id,
            "id_medico": medico_id,
            "fecha": _proximo_dia_semana(6).isoformat(),
            "hora": "09:00:00",
        },
    )
    assert res.status_code == 409
    assert "E-006" in res.json()["detail"]


def test_cancelar_cita_libera_slot(client, auth_as, seed_users):
    """CU-08: cancelar una cita libera el horario.

    La tesis (P2.4 / CU-07 / CU-08) exige que al cancelar o reprogramar,
    el horario quede libre. La implementación usa un índice único PARCIAL
    sobre (id_medico, fecha, hora) WHERE estado <> 'cancelada', lo que
    permite reutilizar el slot tras la cancelación sin perder unicidad
    para las citas activas.
    """
    auth_as("secretaria")
    paciente_id = _crear_paciente(client)
    medico_id = seed_users["medico"].id
    fecha = _proximo_dia_semana(2).isoformat()  # martes

    primera = client.post(
        "/api/v1/citas",
        json={
            "id_paciente": paciente_id,
            "id_medico": medico_id,
            "fecha": fecha,
            "hora": "09:00:00",
        },
    ).json()

    # Cancelar la primera (soft delete → estado='cancelada')
    cancel = client.delete(f"/api/v1/citas/{primera['id']}")
    assert cancel.status_code == 204

    # Crear una nueva en el mismo slot: debe permitirse
    segunda = client.post(
        "/api/v1/citas",
        json={
            "id_paciente": paciente_id,
            "id_medico": medico_id,
            "fecha": fecha,
            "hora": "09:00:00",
        },
    )
    assert segunda.status_code == 201, segunda.text
    assert segunda.json()["id"] != primera["id"]


def test_reprogramar_cita_libera_horario_anterior(client, auth_as, seed_users):
    """CU-07: reprogramar una cita libera el horario anterior.

    Después de mover la cita A de las 09:00 a las 10:00, debería ser posible
    crear una NUEVA cita B en las 09:00 originales.
    """
    auth_as("secretaria")
    paciente_id = _crear_paciente(client)
    medico_id = seed_users["medico"].id
    fecha = _proximo_dia_semana(3).isoformat()  # miércoles

    cita_a = client.post(
        "/api/v1/citas",
        json={
            "id_paciente": paciente_id,
            "id_medico": medico_id,
            "fecha": fecha,
            "hora": "09:00:00",
        },
    ).json()

    # Reprogramar A: 09:00 -> 10:00
    patch = client.patch(f"/api/v1/citas/{cita_a['id']}", json={"hora": "10:00:00"})
    assert patch.status_code == 200, patch.text

    # Crear B en las 09:00 originales: debe permitirse
    cita_b = client.post(
        "/api/v1/citas",
        json={
            "id_paciente": paciente_id,
            "id_medico": medico_id,
            "fecha": fecha,
            "hora": "09:00:00",
        },
    )
    assert cita_b.status_code == 201, cita_b.text


def test_calendar_feed(client, auth_as, seed_users):
    auth_as("secretaria")
    paciente_id = _crear_paciente(client)
    medico_id = seed_users["medico"].id
    fecha = _proximo_dia_semana(3)  # miércoles

    client.post(
        "/api/v1/citas",
        json={
            "id_paciente": paciente_id,
            "id_medico": medico_id,
            "fecha": fecha.isoformat(),
            "hora": "11:00:00",
        },
    )

    start = (fecha - timedelta(days=7)).isoformat()
    end = (fecha + timedelta(days=7)).isoformat()
    res = client.get(f"/api/v1/citas/calendar?start={start}&end={end}")
    assert res.status_code == 200
    eventos = res.json()
    assert len(eventos) == 1
    assert eventos[0]["color"] == "#2563eb"  # pendiente
    assert "Ana García" in eventos[0]["title"]
