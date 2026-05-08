"""Tests Mejora 1: vinculación usuario↔médico desde filtro y validación backend."""


def _crear_usuario_medico(client, email="dr.nuevo@test.do", nombre="Dr. Nuevo"):
    res = client.post(
        "/api/v1/usuarios",
        json={"nombre": nombre, "email": email, "password": "Medico*2026", "rol": "medico"},
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
