"""Tests Mejora 1: vinculación usuario↔médico desde filtro y validación backend."""
from sqlmodel import select

from app.models import RolUsuario, Usuario
from tests.conftest import TEST_PASSWORD


def _crear_usuario_medico(client, email="dr.nuevo@test.do", nombre="Dr. Nuevo"):
    res = client.post(
        "/api/v1/usuarios",
        json={"nombre": nombre, "email": email, "password": TEST_PASSWORD, "rol": "medico"},
    )
    assert res.status_code == 201, res.text
    return res.json()


def test_filtrar_usuarios_rol_medico_sin_perfil(client, auth_as, seed_users):
    """GET /usuarios?rol=medico&sin_perfil_medico=true excluye los ya vinculados."""
    auth_as("admin")
    nuevo = _crear_usuario_medico(client)

    res = client.get("/api/v1/usuarios?rol=medico&sin_perfil_medico=true")
    assert res.status_code == 200
    ids = [u["id"] for u in res.json()]

    assert nuevo["id"] in ids
    # El medico_user del seed YA tiene perfil → no debe aparecer
    assert seed_users["medico_user"].id not in ids


def test_filtrar_usuarios_sol_rol(client, auth_as, seed_users):
    """GET /usuarios?rol=medico devuelve solo usuarios con ese rol."""
    auth_as("admin")
    res = client.get("/api/v1/usuarios?rol=medico")
    assert res.status_code == 200
    for u in res.json():
        assert u["rol"] == "medico"


def test_crear_medico_con_id_usuario_valido(client, auth_as, seed_users):
    """POST /medicos con id_usuario de rol medico sin perfil previo → 201."""
    auth_as("admin")
    nuevo = _crear_usuario_medico(client, email="dr.cardio@test.do")

    res = client.post(
        "/api/v1/medicos",
        json={"id_usuario": nuevo["id"], "nombre": "Dr. Cardio", "especialidad": "Cardiología"},
    )
    assert res.status_code == 201, res.text
    assert res.json()["id_usuario"] == nuevo["id"]


def test_crear_medico_con_id_usuario_ya_vinculado_retorna_422(client, auth_as, seed_users):
    """POST /medicos con id_usuario que ya tiene perfil → 422."""
    auth_as("admin")
    res = client.post(
        "/api/v1/medicos",
        json={
            "id_usuario": seed_users["medico_user"].id,
            "nombre": "Duplicado",
            "especialidad": "Pediatría",
        },
    )
    assert res.status_code == 422, res.text
    assert "vinculado" in res.json()["detail"]


def test_crear_medico_con_id_usuario_no_medico_retorna_422(client, auth_as, seed_users):
    """POST /medicos con id_usuario de rol admin → 422."""
    auth_as("admin")
    res = client.post(
        "/api/v1/medicos",
        json={
            "id_usuario": seed_users["admin"].id,
            "nombre": "Error Test",
            "especialidad": "Pediatría",
        },
    )
    assert res.status_code == 422, res.text
    assert "no es válido" in res.json()["detail"]


# ── POST /medicos/con-usuario ─────────────────────────────────────────────────

def test_crear_medico_con_usuario_exito(client, auth_as, session):
    """POST /medicos/con-usuario crea usuario (rol medico) y médico en una sola operación."""
    auth_as("admin")
    res = client.post(
        "/api/v1/medicos/con-usuario",
        json={
            "usuario": {
                "nombre": "Dr. Combinado",
                "email": "drcombinado@test.do",
                "password": TEST_PASSWORD,
            },
            "medico": {
                "nombre": "Dr. Combinado",
                "especialidad": "Neurología",
                "telefono": "8090001234",
            },
        },
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["nombre"] == "Dr. Combinado"
    assert body["especialidad"] == "Neurología"
    assert body["id_usuario"] is not None

    u = session.exec(select(Usuario).where(Usuario.email == "drcombinado@test.do")).first()
    assert u is not None
    assert u.rol == RolUsuario.medico


def test_crear_medico_con_usuario_rollback(client, auth_as, session):
    """Si los datos del médico son inválidos (422), el usuario tampoco se persiste."""
    auth_as("admin")
    email = "rollback@test.do"
    res = client.post(
        "/api/v1/medicos/con-usuario",
        json={
            "usuario": {
                "nombre": "Dr. Rollback",
                "email": email,
                "password": TEST_PASSWORD,
            },
            "medico": {
                "nombre": "Dr. Rollback",
                "especialidad": "X",  # 1 carácter: falla min_length=2 → 422 antes de tocar la BD
            },
        },
    )
    assert res.status_code == 422

    u = session.exec(select(Usuario).where(Usuario.email == email)).first()
    assert u is None, "El usuario no debe quedar persistido cuando el médico es inválido"


def test_crear_medico_con_usuario_email_duplicado(client, auth_as, seed_users):
    """POST /medicos/con-usuario con email ya registrado → 409."""
    auth_as("admin")
    res = client.post(
        "/api/v1/medicos/con-usuario",
        json={
            "usuario": {
                "nombre": "Duplicado",
                "email": "med@test.do",  # ya existe en seed_users
                "password": TEST_PASSWORD,
            },
            "medico": {
                "nombre": "Duplicado",
                "especialidad": "Cardiología",
            },
        },
    )
    assert res.status_code == 409, res.text
    assert "registrado" in res.json()["detail"]
