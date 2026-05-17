"""Tests del cambio de contraseña por administrador.

Endpoint: PATCH /api/v1/usuarios/{id}/password — solo admin.
Reusa la política existente (min 8, max 128) y la función hash_password.
La auditoría NO debe exponer la contraseña ni el hash.
"""
from sqlmodel import select

from app.core.security import verify_password
from app.models import AccionAuditoria, Auditoria, Usuario
from tests.conftest import TEST_PASSWORD


NUEVA = "ClaveNueva!2026"


def test_admin_puede_cambiar_password_de_usuario(client, auth_as, session, seed_users):
    auth_as("admin")
    sec_id = seed_users["secretaria"].id

    res = client.patch(
        f"/api/v1/usuarios/{sec_id}/password",
        json={"nueva_password": NUEVA},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["id"] == sec_id
    assert "password_hash" not in body  # nunca exponer hash en la respuesta

    # Verificar en BD que el hash cambió y la nueva contraseña verifica
    session.expire_all()
    user = session.get(Usuario, sec_id)
    assert verify_password(NUEVA, user.password_hash)
    assert not verify_password(TEST_PASSWORD, user.password_hash)


def test_secretaria_no_puede_cambiar_passwords_403(client, auth_as, seed_users):
    auth_as("secretaria")
    target_id = seed_users["medico_user"].id
    res = client.patch(
        f"/api/v1/usuarios/{target_id}/password",
        json={"nueva_password": NUEVA},
    )
    assert res.status_code == 403


def test_medico_no_puede_cambiar_passwords_403(client, auth_as, seed_users):
    auth_as("medico")
    target_id = seed_users["secretaria"].id
    res = client.patch(
        f"/api/v1/usuarios/{target_id}/password",
        json={"nueva_password": NUEVA},
    )
    assert res.status_code == 403


def test_cambio_password_respeta_politica(client, auth_as, seed_users):
    auth_as("admin")
    target_id = seed_users["secretaria"].id

    # Menos de 8 caracteres → 422
    res = client.patch(
        f"/api/v1/usuarios/{target_id}/password",
        json={"nueva_password": "abc123"},
    )
    assert res.status_code == 422

    # Más de 128 caracteres → 422
    res = client.patch(
        f"/api/v1/usuarios/{target_id}/password",
        json={"nueva_password": "x" * 129},
    )
    assert res.status_code == 422

    # Exactamente 8 caracteres → 200
    res = client.patch(
        f"/api/v1/usuarios/{target_id}/password",
        json={"nueva_password": "12345678"},
    )
    assert res.status_code == 200


def test_cambio_password_genera_auditoria_sin_exponer_hash(
    client, auth_as, session, seed_users
):
    auth_as("admin")
    sec = seed_users["secretaria"]

    res = client.patch(
        f"/api/v1/usuarios/{sec.id}/password",
        json={"nueva_password": NUEVA},
    )
    assert res.status_code == 200

    # Releer el hash desde la BD (ya cambió)
    session.expire_all()
    user_db = session.get(Usuario, sec.id)
    nuevo_hash = user_db.password_hash

    logs = session.exec(
        select(Auditoria)
        .where(Auditoria.tabla_afectada == "usuarios")
        .where(Auditoria.id_registro == sec.id)
        .order_by(Auditoria.id.desc())
    ).all()
    assert len(logs) >= 1
    log = logs[0]
    assert log.accion == AccionAuditoria.UPDATE
    assert log.nombre_usuario == seed_users["admin"].nombre

    # El detalle de auditoría NO debe contener la contraseña ni el hash
    detalle = log.detalle or ""
    assert NUEVA not in detalle
    assert nuevo_hash not in detalle
    assert "$2b$" not in detalle  # prefijo típico de bcrypt
    assert "password_hash" not in detalle


def test_usuario_puede_loguear_con_nueva_password(client, auth_as, seed_users):
    auth_as("admin")
    sec = seed_users["secretaria"]

    res = client.patch(
        f"/api/v1/usuarios/{sec.id}/password",
        json={"nueva_password": NUEVA},
    )
    assert res.status_code == 200

    # Quitar override de auth para hacer login real
    from app.api.deps import get_current_user
    from app.main import app
    app.dependency_overrides.pop(get_current_user, None)

    # Login con la nueva contraseña → 200
    res = client.post(
        "/api/v1/auth/login",
        data={"username": sec.email, "password": NUEVA},
    )
    assert res.status_code == 200
    assert res.json()["rol"] == "secretaria"

    # Login con la vieja → 401
    res = client.post(
        "/api/v1/auth/login",
        data={"username": sec.email, "password": TEST_PASSWORD},
    )
    assert res.status_code == 401


def test_cambiar_password_usuario_inexistente_404(client, auth_as):
    auth_as("admin")
    res = client.patch(
        "/api/v1/usuarios/99999/password",
        json={"nueva_password": NUEVA},
    )
    assert res.status_code == 404
