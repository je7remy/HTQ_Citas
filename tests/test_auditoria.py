"""Tests de auditoría: cada acción CRUD/LOGIN debe dejar registro.

Verifica que el servicio `registrar_auditoria` se invoca correctamente
desde cada router y que comparte transacción con la operación principal.
"""
from datetime import date, timedelta

from sqlmodel import Session, select

from app.models import AccionAuditoria, Auditoria
from tests.conftest import TEST_PASSWORD


def _proximo_lunes() -> date:
    hoy = date.today()
    for offset in range(1, 8):
        d = hoy + timedelta(days=offset)
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
    assert res.status_code == 201
    return res.json()["id"]


def _logs(session: Session, tabla: str | None = None, accion: AccionAuditoria | None = None):
    stmt = select(Auditoria)
    if tabla:
        stmt = stmt.where(Auditoria.tabla_afectada == tabla)
    if accion:
        stmt = stmt.where(Auditoria.accion == accion)
    return session.exec(stmt).all()


# ---------- LOGIN ----------
def test_login_genera_auditoria(client, session, seed_users):
    res = client.post(
        "/api/v1/auth/login",
        data={"username": "admin@test.do", "password": TEST_PASSWORD},
    )
    assert res.status_code == 200

    logs = _logs(session, tabla="usuarios", accion=AccionAuditoria.LOGIN)
    assert len(logs) == 1
    assert logs[0].id_usuario == seed_users["admin"].id
    assert "admin@test.do" in (logs[0].detalle or "")


def test_login_fallido_no_genera_auditoria(client, session, seed_users):
    """Solo los logins exitosos se auditan (los fallidos no llegan al servicio)."""
    client.post(
        "/api/v1/auth/login",
        data={"username": "admin@test.do", "password": "wrong"},
    )
    assert len(_logs(session, accion=AccionAuditoria.LOGIN)) == 0


# ---------- PACIENTES ----------
def test_crear_paciente_genera_auditoria(client, session, auth_as, seed_users):
    auth_as("secretaria")
    paciente_id = _crear_paciente(client)

    logs = _logs(session, tabla="pacientes", accion=AccionAuditoria.CREATE)
    assert len(logs) == 1
    log = logs[0]
    assert log.id_registro == paciente_id
    assert log.id_usuario == seed_users["secretaria"].id
    assert "00112345678" in (log.detalle or "")


def test_actualizar_paciente_genera_auditoria(client, session, auth_as):
    auth_as("secretaria")
    paciente_id = _crear_paciente(client)

    client.patch(f"/api/v1/pacientes/{paciente_id}", json={"telefono": "8095559999"})

    logs = _logs(session, tabla="pacientes", accion=AccionAuditoria.UPDATE)
    assert len(logs) == 1
    assert logs[0].id_registro == paciente_id
    assert "telefono" in (logs[0].detalle or "")


def test_eliminar_paciente_genera_auditoria(client, session, auth_as):
    auth_as("secretaria")
    paciente_id = _crear_paciente(client)

    client.delete(f"/api/v1/pacientes/{paciente_id}")

    logs = _logs(session, tabla="pacientes", accion=AccionAuditoria.DELETE)
    assert len(logs) == 1
    assert logs[0].id_registro == paciente_id


def test_e007_fallo_no_deja_log_huerfano(client, session, auth_as):
    """Si la creación falla por cédula duplicada (E-007), NO debe quedar
    registro de auditoría — confirma la atomicidad transaccional."""
    auth_as("secretaria")
    _crear_paciente(client)  # primera vez, ok (1 log CREATE)

    res = client.post(  # segunda vez, falla por cédula duplicada
        "/api/v1/pacientes",
        json={
            "cedula": "00112345678",
            "nombre": "Otro",
            "apellidos": "Apellidos",
            "telefono": "8090000000",
        },
    )
    assert res.status_code == 409
    assert "E-007" in res.json()["detail"]

    logs = _logs(session, tabla="pacientes", accion=AccionAuditoria.CREATE)
    assert len(logs) == 1, "El log del intento fallido no debe persistir"


# ---------- CITAS ----------
def test_crear_cita_genera_auditoria(client, session, auth_as, seed_users):
    auth_as("secretaria")
    paciente_id = _crear_paciente(client)

    res = client.post(
        "/api/v1/citas",
        json={
            "id_paciente": paciente_id,
            "id_medico": seed_users["medico"].id,
            "fecha": _proximo_lunes().isoformat(),
            "hora": "09:00:00",
        },
    )
    assert res.status_code == 201
    cita_id = res.json()["id"]

    logs = _logs(session, tabla="citas", accion=AccionAuditoria.CREATE)
    assert len(logs) == 1
    assert logs[0].id_registro == cita_id
    assert logs[0].id_usuario == seed_users["secretaria"].id


def test_cancelar_cita_genera_auditoria_delete(client, session, auth_as, seed_users):
    auth_as("secretaria")
    paciente_id = _crear_paciente(client)

    cita = client.post(
        "/api/v1/citas",
        json={
            "id_paciente": paciente_id,
            "id_medico": seed_users["medico"].id,
            "fecha": _proximo_lunes().isoformat(),
            "hora": "09:00:00",
        },
    ).json()

    client.delete(f"/api/v1/citas/{cita['id']}")

    logs = _logs(session, tabla="citas", accion=AccionAuditoria.DELETE)
    assert len(logs) == 1
    assert logs[0].id_registro == cita["id"]
    assert "Cancelación" in (logs[0].detalle or "")


def test_e005_fallo_no_deja_log_huerfano(client, session, auth_as, seed_users):
    """Si la cita choca contra E-005, NO debe quedar log CREATE del intento."""
    auth_as("secretaria")
    paciente_id = _crear_paciente(client)
    medico_id = seed_users["medico"].id
    fecha = _proximo_lunes().isoformat()

    client.post(
        "/api/v1/citas",
        json={
            "id_paciente": paciente_id,
            "id_medico": medico_id,
            "fecha": fecha,
            "hora": "09:00:00",
        },
    )  # ok → 1 log

    res = client.post(
        "/api/v1/citas",
        json={
            "id_paciente": paciente_id,
            "id_medico": medico_id,
            "fecha": fecha,
            "hora": "09:00:00",
        },
    )
    assert res.status_code == 409

    logs = _logs(session, tabla="citas", accion=AccionAuditoria.CREATE)
    assert len(logs) == 1, "El intento fallido no debe haber dejado log"


# ---------- MÉDICOS ----------
def test_crear_medico_genera_auditoria(client, session, auth_as, seed_users):
    auth_as("admin")
    res = client.post(
        "/api/v1/medicos",
        json={"nombre": "Dra. Z", "especialidad": "Pediatría"},
    )
    assert res.status_code == 201

    logs = _logs(session, tabla="medicos", accion=AccionAuditoria.CREATE)
    assert len(logs) == 1
    assert logs[0].id_usuario == seed_users["admin"].id
    assert "Dra. Z" in (logs[0].detalle or "")


# ---------- CU-15: Consulta de auditoría ----------
def test_cu15_admin_consulta_auditoria(client, auth_as):
    """El admin debe poder listar el log de auditoría."""
    auth_as("secretaria")
    _crear_paciente(client)  # genera 1 log CREATE pacientes

    auth_as("admin")
    res = client.get("/api/v1/auditoria")
    assert res.status_code == 200
    body = res.json()
    assert "items" in body
    assert "total" in body
    assert body["total"] >= 1
    assert any(i["tabla_afectada"] == "pacientes" for i in body["items"])


def test_cu15_secretaria_no_puede_consultar_auditoria(client, auth_as):
    """RBAC: solo admin puede consultar auditoría."""
    auth_as("secretaria")
    res = client.get("/api/v1/auditoria")
    assert res.status_code == 403


def test_cu15_filtro_por_accion(client, auth_as):
    auth_as("secretaria")
    pid = _crear_paciente(client)
    client.patch(f"/api/v1/pacientes/{pid}", json={"telefono": "8090000000"})

    auth_as("admin")
    res = client.get("/api/v1/auditoria?accion=UPDATE")
    assert res.status_code == 200
    items = res.json()["items"]
    assert len(items) >= 1
    assert all(i["accion"] == "UPDATE" for i in items)


def test_cu15_filtro_por_tabla(client, auth_as):
    auth_as("secretaria")
    _crear_paciente(client)

    auth_as("admin")
    res = client.get("/api/v1/auditoria?tabla=pacientes")
    assert res.status_code == 200
    items = res.json()["items"]
    assert all(i["tabla_afectada"] == "pacientes" for i in items)


def test_cu15_paginacion(client, auth_as):
    auth_as("secretaria")
    # Generar varios logs
    for i in range(5):
        client.post(
            "/api/v1/pacientes",
            json={
                "cedula": f"0011234567{i}",
                "nombre": f"Paciente{i}",
                "apellidos": "Apellidos",
                "telefono": "8090000000",
            },
        )

    auth_as("admin")
    res = client.get("/api/v1/auditoria?limit=2&offset=0")
    assert res.status_code == 200
    body = res.json()
    assert len(body["items"]) == 2
    assert body["total"] >= 5
    assert body["limit"] == 2
    assert body["offset"] == 0
