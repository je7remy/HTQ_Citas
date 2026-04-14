"""Tests del módulo de pacientes — incluye E-007 (cédula duplicada)."""


def _paciente_valido(**overrides):
    base = {
        "cedula": "00112345678",
        "nombre": "María",
        "apellidos": "Rodríguez",
        "telefono": "8095550100",
    }
    base.update(overrides)
    return base


def test_crear_paciente_ok(client, auth_as):
    auth_as("secretaria")
    res = client.post("/api/v1/pacientes", json=_paciente_valido())
    assert res.status_code == 201
    body = res.json()
    assert body["cedula"] == "00112345678"
    assert body["id"] > 0


def test_e007_cedula_duplicada(client, auth_as):
    auth_as("secretaria")
    client.post("/api/v1/pacientes", json=_paciente_valido())
    res = client.post("/api/v1/pacientes", json=_paciente_valido(nombre="Otro"))
    assert res.status_code == 409
    assert "E-007" in res.json()["detail"]


def test_cedula_invalida_no_numerica(client, auth_as):
    auth_as("secretaria")
    res = client.post("/api/v1/pacientes", json=_paciente_valido(cedula="ABCDEFGHIJK"))
    assert res.status_code == 422


def test_cedula_invalida_longitud(client, auth_as):
    auth_as("secretaria")
    res = client.post("/api/v1/pacientes", json=_paciente_valido(cedula="123"))
    assert res.status_code == 422


def test_cedula_normaliza_guiones(client, auth_as):
    auth_as("secretaria")
    res = client.post("/api/v1/pacientes", json=_paciente_valido(cedula="001-1234567-8"))
    assert res.status_code == 201
    assert res.json()["cedula"] == "00112345678"


def test_buscar_pacientes(client, auth_as):
    auth_as("secretaria")
    client.post("/api/v1/pacientes", json=_paciente_valido(cedula="00100000001", nombre="Juan"))
    client.post("/api/v1/pacientes", json=_paciente_valido(cedula="00100000002", nombre="Pedro"))

    res = client.get("/api/v1/pacientes?q=Juan")
    assert res.status_code == 200
    assert len(res.json()) == 1
    assert res.json()[0]["nombre"] == "Juan"


def test_actualizar_paciente(client, auth_as):
    auth_as("secretaria")
    creado = client.post("/api/v1/pacientes", json=_paciente_valido()).json()
    res = client.patch(f"/api/v1/pacientes/{creado['id']}", json={"telefono": "8095559999"})
    assert res.status_code == 200
    assert res.json()["telefono"] == "8095559999"
