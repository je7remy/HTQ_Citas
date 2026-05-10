"""Tests del endpoint de historial médico (Mejora 3.3)."""
from datetime import date, timedelta


def _pasado_lunes(offset_semanas: int = 0) -> date:
    """Devuelve un lunes pasado, opcionalmente N semanas atrás del más reciente."""
    hoy = date.today()
    for offset in range(1, 15):
        d = hoy - timedelta(days=offset)
        if d.isoweekday() == 1:
            return d - timedelta(weeks=offset_semanas)
    raise RuntimeError("unreachable")


def _crear_paciente(client, auth_as, cedula="00112345678") -> int:
    auth_as("secretaria")
    res = client.post(
        "/api/v1/pacientes",
        json={
            "cedula": cedula,
            "nombre": "Ana", "apellidos": "García",
            "sexo": "femenino", "fecha_nacimiento": "1990-04-12",
            "telefono": "8095550100",
        },
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


def _crear_consulta(client, auth_as, seed_users, paciente_id, hora="09:00:00", offset_semanas=0):
    auth_as("secretaria")
    cita_res = client.post(
        "/api/v1/citas",
        json={
            "id_paciente": paciente_id,
            "id_medico": seed_users["medico"].id,
            "fecha": _pasado_lunes(offset_semanas).isoformat(),
            "hora": hora,
        },
    )
    assert cita_res.status_code == 201, cita_res.text
    cita_id = cita_res.json()["id"]
    auth_as("medico")
    res = client.post(
        "/api/v1/consultas",
        json={"id_cita": cita_id, "condicion_principal": f"Diagnóstico {hora}"},
    )
    assert res.status_code == 201, res.text
    return res.json()


def test_historial_lista_consultas_orden_desc(client, auth_as, seed_users):
    """El historial devuelve las consultas atendidas ordenadas por fecha DESC."""
    paciente_id = _crear_paciente(client, auth_as)
    _crear_consulta(client, auth_as, seed_users, paciente_id, hora="09:00:00", offset_semanas=2)
    _crear_consulta(client, auth_as, seed_users, paciente_id, hora="10:00:00", offset_semanas=0)

    auth_as("secretaria")
    res = client.get(f"/api/v1/pacientes/{paciente_id}/historial-medico")
    assert res.status_code == 200
    items = res.json()
    assert len(items) == 2
    # El más reciente primero
    f0 = date.fromisoformat(items[0]["fecha_consulta"])
    f1 = date.fromisoformat(items[1]["fecha_consulta"])
    assert f0 >= f1


def test_historial_filtra_por_medico(client, auth_as, seed_users):
    """El parámetro medico_id filtra correctamente."""
    paciente_id = _crear_paciente(client, auth_as)
    _crear_consulta(client, auth_as, seed_users, paciente_id)

    medico_id = seed_users["medico"].id
    auth_as("secretaria")
    res_match = client.get(
        f"/api/v1/pacientes/{paciente_id}/historial-medico?medico_id={medico_id}"
    )
    assert res_match.status_code == 200
    assert len(res_match.json()) == 1

    res_otro = client.get(
        f"/api/v1/pacientes/{paciente_id}/historial-medico?medico_id=99999"
    )
    assert res_otro.status_code == 200
    assert res_otro.json() == []


def test_historial_paciente_sin_consultas_retorna_vacio(client, auth_as):
    """Paciente sin historial → lista vacía."""
    paciente_id = _crear_paciente(client, auth_as)
    res = client.get(f"/api/v1/pacientes/{paciente_id}/historial-medico")
    assert res.status_code == 200
    assert res.json() == []


def test_historial_paciente_inexistente_retorna_404(client, auth_as):
    auth_as("secretaria")
    res = client.get("/api/v1/pacientes/99999/historial-medico")
    assert res.status_code == 404


def test_historial_incluye_los_5_campos_clinicos(client, auth_as, seed_users):
    """Cada item del historial expone los 5 campos del diagnóstico estructurado."""
    paciente_id = _crear_paciente(client, auth_as)
    auth_as("secretaria")
    cita_res = client.post(
        "/api/v1/citas",
        json={
            "id_paciente": paciente_id,
            "id_medico": seed_users["medico"].id,
            "fecha": _pasado_lunes().isoformat(),
            "hora": "09:00:00",
        },
    )
    cita_id = cita_res.json()["id"]
    auth_as("medico")
    client.post(
        "/api/v1/consultas",
        json={
            "id_cita": cita_id,
            "motivo_consulta": "Dolor",
            "examen_fisico": "Sensible",
            "condicion_principal": "Lumbalgia",
            "condiciones_secundarias": "—",
            "tratamiento": "AINES",
        },
    )

    auth_as("secretaria")
    items = client.get(f"/api/v1/pacientes/{paciente_id}/historial-medico").json()
    assert len(items) == 1
    item = items[0]
    for k in ["motivo_consulta", "examen_fisico", "condicion_principal",
              "condiciones_secundarias", "tratamiento", "medico", "especialidad"]:
        assert k in item
    assert item["condicion_principal"] == "Lumbalgia"
