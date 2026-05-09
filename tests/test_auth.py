"""Tests de autenticación y RBAC."""
from tests.conftest import TEST_PASSWORD


def test_login_exitoso(client, seed_users):
    res = client.post(
        "/api/v1/auth/login",
        data={"username": "admin@test.do", "password": TEST_PASSWORD},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["token_type"] == "bearer"
    assert body["rol"] == "admin"
    assert body["access_token"]


def test_login_password_incorrecto(client, seed_users):
    res = client.post(
        "/api/v1/auth/login",
        data={"username": "admin@test.do", "password": "wrong"},
    )
    assert res.status_code == 401


def test_login_email_inexistente(client, seed_users):
    res = client.post(
        "/api/v1/auth/login",
        data={"username": "noexiste@test.do", "password": "x"},
    )
    assert res.status_code == 401


def test_endpoint_protegido_sin_token(client):
    res = client.get("/api/v1/pacientes")
    assert res.status_code == 401


def test_rbac_secretaria_no_puede_crear_medico(client, auth_as):
    auth_as("secretaria")
    res = client.post(
        "/api/v1/medicos",
        json={"nombre": "Dr. X", "especialidad": "Cardiología"},
    )
    assert res.status_code == 403


def test_rbac_admin_si_puede_crear_medico(client, auth_as):
    auth_as("admin")
    res = client.post(
        "/api/v1/medicos",
        json={"nombre": "Dr. Y", "especialidad": "Cirugía General"},
    )
    assert res.status_code == 201
    assert res.json()["nombre"] == "Y"
