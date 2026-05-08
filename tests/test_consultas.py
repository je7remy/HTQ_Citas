"""Tests Mejora 2: bloqueo de consulta antes del horario programado de la cita."""
from datetime import date, timedelta


def _proximo_lunes() -> date:
    hoy = date.today()
    for offset in range(1, 8):
        d = hoy + timedelta(days=offset)
        if d.isoweekday() == 1:
            return d
    raise RuntimeError("unreachable")


def _pasado_lunes() -> date:
    hoy = date.today()
    for offset in range(1, 15):
        d = hoy - timedelta(days=offset)
        if d.isoweekday() == 1:
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


def test_registrar_consulta_cita_futura_retorna_400(client, auth_as, seed_users):
    """POST /consultas con cita en fecha futura debe retornar 400."""
    auth_as("secretaria")
    paciente_id = _crear_paciente(client)
    cita_res = client.post(
        "/api/v1/citas",
        json={
            "id_paciente": paciente_id,
            "id_medico": seed_users["medico"].id,
            "fecha": _proximo_lunes().isoformat(),
            "hora": "09:00:00",
        },
    )
    assert cita_res.status_code == 201, cita_res.text
    cita_id = cita_res.json()["id"]

    auth_as("medico")
    res = client.post(
        "/api/v1/consultas",
        json={"id_cita": cita_id, "observaciones": "Diagnóstico anticipado"},
    )
    assert res.status_code == 400, res.text
    assert "antes del horario" in res.json()["detail"]


def test_registrar_consulta_cita_pasada_retorna_201(client, auth_as, seed_users):
    """POST /consultas con cita en fecha pasada debe retornar 201."""
    auth_as("secretaria")
    paciente_id = _crear_paciente(client)
    cita_res = client.post(
        "/api/v1/citas",
        json={
            "id_paciente": paciente_id,
            "id_medico": seed_users["medico"].id,
            "fecha": _pasado_lunes().isoformat(),
            "hora": "09:00:00",
        },
    )
    assert cita_res.status_code == 201, cita_res.text
    cita_id = cita_res.json()["id"]

    auth_as("medico")
    res = client.post(
        "/api/v1/consultas",
        json={"id_cita": cita_id, "observaciones": "Diagnóstico post-cita"},
    )
    assert res.status_code == 201, res.text
    assert res.json()["id_cita"] == cita_id
