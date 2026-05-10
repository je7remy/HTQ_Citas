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
            "sexo": "femenino",
            "fecha_nacimiento": "1990-04-12",
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
        json={"id_cita": cita_id, "condicion_principal": "Diagnóstico anticipado"},
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
        json={"id_cita": cita_id, "condicion_principal": "Diagnóstico post-cita"},
    )
    assert res.status_code == 201, res.text
    assert res.json()["id_cita"] == cita_id


# ---------- Mejora 3.2: diagnóstico estructurado ----------
def _crear_cita_pasada(client, seed_users) -> int:
    """Helper: crea paciente y cita en lunes pasado para poder registrar consulta."""
    paciente_id = _crear_paciente(client)
    res = client.post(
        "/api/v1/citas",
        json={
            "id_paciente": paciente_id,
            "id_medico": seed_users["medico"].id,
            "fecha": _pasado_lunes().isoformat(),
            "hora": "09:00:00",
        },
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


def test_consulta_sin_condicion_principal_retorna_422(client, auth_as, seed_users):
    auth_as("secretaria")
    cita_id = _crear_cita_pasada(client, seed_users)
    auth_as("medico")
    res = client.post("/api/v1/consultas", json={"id_cita": cita_id})
    assert res.status_code == 422


def test_consulta_solo_condicion_principal_funciona(client, auth_as, seed_users):
    auth_as("secretaria")
    cita_id = _crear_cita_pasada(client, seed_users)
    auth_as("medico")
    res = client.post(
        "/api/v1/consultas",
        json={"id_cita": cita_id, "condicion_principal": "Lumbalgia mecánica"},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["condicion_principal"] == "Lumbalgia mecánica"
    assert body["motivo_consulta"] is None


def test_consulta_completa_5_campos(client, auth_as, seed_users):
    """POST /consultas con los 5 campos clínicos los persiste y los devuelve."""
    auth_as("secretaria")
    cita_id = _crear_cita_pasada(client, seed_users)
    auth_as("medico")
    payload = {
        "id_cita": cita_id,
        "motivo_consulta": "Dolor lumbar de 3 semanas",
        "examen_fisico": "Sensibilidad L4-L5 a la palpación",
        "condicion_principal": "Hernia discal L4-L5",
        "condiciones_secundarias": "Sobrepeso, sedentarismo",
        "tratamiento": "AINES, fisioterapia 3x/sem por 6 semanas",
    }
    res = client.post("/api/v1/consultas", json=payload)
    assert res.status_code == 201, res.text
    body = res.json()
    for k in ["motivo_consulta", "examen_fisico", "condicion_principal",
              "condiciones_secundarias", "tratamiento"]:
        assert body[k] == payload[k]
