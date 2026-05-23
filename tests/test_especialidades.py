"""Tests CU-17 — CRUD del catálogo de especialidades."""
from sqlmodel import select

from app.models import Auditoria, Especialidad, Medico
from tests.conftest import ESPECIALIDADES_HTQPJB_SEED, TEST_PASSWORD


# ──────────────── GET /especialidades ────────────────

def test_get_especialidades_listado_completo(client, auth_as, seed_users):
    """Sin filtros devuelve las 18 sembradas por la migración (todas activas)."""
    auth_as("admin")
    res = client.get("/api/v1/especialidades")
    assert res.status_code == 200, res.text
    body = res.json()
    assert len(body) == 18
    nombres = {e["nombre"] for e in body}
    assert nombres == set(ESPECIALIDADES_HTQPJB_SEED)
    assert all(e["activa"] is True for e in body)


def test_get_especialidades_solo_activas(client, auth_as, seed_users, session):
    """Con `activa=true` filtra correctamente; al desactivar una desaparece."""
    auth_as("admin")
    esp = session.exec(
        select(Especialidad).where(Especialidad.nombre == "Medicina Interna")
    ).first()
    esp.activa = False
    session.add(esp)
    session.commit()

    res = client.get("/api/v1/especialidades?activa=true")
    assert res.status_code == 200
    nombres = {e["nombre"] for e in res.json()}
    assert "Medicina Interna" not in nombres
    assert len(res.json()) == 17

    res_todas = client.get("/api/v1/especialidades")
    assert len(res_todas.json()) == 18


def test_get_especialidades_busqueda_por_nombre(client, auth_as, seed_users):
    """`q` es coincidencia parcial case-insensitive."""
    auth_as("admin")
    res = client.get("/api/v1/especialidades?q=cirug")
    assert res.status_code == 200
    nombres = [e["nombre"] for e in res.json()]
    assert len(nombres) >= 6  # hay al menos 7 "Cirugía …" en el seed
    assert all("cirug" in n.lower() for n in nombres)


def test_get_especialidades_accesible_por_secretaria(client, auth_as, seed_users):
    """Lectura abierta a cualquier rol autenticado."""
    auth_as("secretaria")
    res = client.get("/api/v1/especialidades")
    assert res.status_code == 200


# ──────────────── POST /especialidades ────────────────

def test_post_especialidad_admin_crea(client, auth_as, seed_users):
    """Admin puede crear; el registro queda activo por defecto."""
    auth_as("admin")
    res = client.post(
        "/api/v1/especialidades",
        json={"nombre": "Dermatología", "descripcion": "Piel y anexos"},
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["nombre"] == "Dermatología"
    assert body["descripcion"] == "Piel y anexos"
    assert body["activa"] is True


def test_post_especialidad_secretaria_forbidden(client, auth_as, seed_users):
    auth_as("secretaria")
    res = client.post("/api/v1/especialidades", json={"nombre": "Dermatología"})
    assert res.status_code == 403


def test_post_especialidad_medico_forbidden(client, auth_as, seed_users):
    auth_as("medico")
    res = client.post("/api/v1/especialidades", json={"nombre": "Dermatología"})
    assert res.status_code == 403


def test_post_especialidad_nombre_duplicado(client, auth_as, seed_users):
    """Comparación case-insensitive: "medicina interna" choca con "Medicina Interna"."""
    auth_as("admin")
    res = client.post(
        "/api/v1/especialidades",
        json={"nombre": "medicina interna"},
    )
    assert res.status_code == 409, res.text
    assert "existe" in res.json()["detail"].lower()


# ──────────────── PATCH /especialidades/{id} ────────────────

def test_patch_especialidad_admin_actualiza(client, auth_as, seed_users, session):
    auth_as("admin")
    esp = session.exec(
        select(Especialidad).where(Especialidad.nombre == "Anestesiología")
    ).first()
    res = client.patch(
        f"/api/v1/especialidades/{esp.id}",
        json={"descripcion": "Manejo del dolor perioperatorio"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["descripcion"] == "Manejo del dolor perioperatorio"


def test_patch_especialidad_renombrar_a_existente_conflict(client, auth_as, seed_users, session):
    auth_as("admin")
    esp = session.exec(
        select(Especialidad).where(Especialidad.nombre == "Anestesiología")
    ).first()
    res = client.patch(
        f"/api/v1/especialidades/{esp.id}",
        json={"nombre": "Medicina Interna"},
    )
    assert res.status_code == 409, res.text


def test_patch_especialidad_rename_propaga_a_medicos(client, auth_as, seed_users, session):
    """Renombrar el catálogo actualiza la columna texto en medicos referenciados."""
    auth_as("admin")
    # El médico del seed_users tiene "Ortopedia y Traumatología".
    medico_id = seed_users["medico"].id
    esp = session.exec(
        select(Especialidad).where(Especialidad.nombre == "Ortopedia y Traumatología")
    ).first()
    res = client.patch(
        f"/api/v1/especialidades/{esp.id}",
        json={"nombre": "Ortopedia"},
    )
    assert res.status_code == 200, res.text
    session.expire_all()
    m = session.get(Medico, medico_id)
    assert m.especialidad == "Ortopedia"


# ──────────────── DELETE /especialidades/{id} ────────────────

def test_delete_especialidad_sin_uso_funciona(client, auth_as, seed_users, session):
    auth_as("admin")
    esp = session.exec(
        select(Especialidad).where(Especialidad.nombre == "Laboratorio Clínico")
    ).first()
    res = client.delete(f"/api/v1/especialidades/{esp.id}")
    assert res.status_code == 204, res.text
    session.expire_all()
    assert session.get(Especialidad, esp.id) is None


def test_delete_especialidad_en_uso_bloquea(client, auth_as, seed_users, session):
    """No se puede eliminar mientras esté asignada como principal."""
    auth_as("admin")
    # Médico del seed usa "Ortopedia y Traumatología".
    esp = session.exec(
        select(Especialidad).where(Especialidad.nombre == "Ortopedia y Traumatología")
    ).first()
    res = client.delete(f"/api/v1/especialidades/{esp.id}")
    assert res.status_code == 409, res.text
    detalle = res.json()["detail"]
    assert "medico" in detalle.lower()
    assert "desactivela" in detalle.lower() or "desactívela" in detalle.lower()


def test_delete_especialidad_secundaria_en_uso_bloquea(client, auth_as, seed_users, session):
    """Asignada como secundaria_1 también bloquea."""
    auth_as("admin")
    # Asigno "Cirugía General" como secundaria al médico del seed.
    medico = seed_users["medico"]
    medico.especialidad_secundaria_1 = "Cirugía General"
    session.add(medico)
    session.commit()

    esp = session.exec(
        select(Especialidad).where(Especialidad.nombre == "Cirugía General")
    ).first()
    res = client.delete(f"/api/v1/especialidades/{esp.id}")
    assert res.status_code == 409, res.text


def test_delete_especialidad_secretaria_forbidden(client, auth_as, seed_users, session):
    auth_as("secretaria")
    esp = session.exec(
        select(Especialidad).where(Especialidad.nombre == "Laboratorio Clínico")
    ).first()
    res = client.delete(f"/api/v1/especialidades/{esp.id}")
    assert res.status_code == 403


# ──────────────── Interacción con el flujo de médicos ────────────────

def test_desactivar_especialidad_la_quita_del_dropdown(client, auth_as, seed_users, session):
    """Tras desactivar, GET /medicos/especialidades ya no la devuelve."""
    auth_as("admin")
    esp = session.exec(
        select(Especialidad).where(Especialidad.nombre == "Oftalmología")
    ).first()
    client.patch(f"/api/v1/especialidades/{esp.id}", json={"activa": False})

    res = client.get("/api/v1/medicos/especialidades")
    assert res.status_code == 200
    assert "Oftalmología" not in res.json()["especialidades"]


def test_reactivar_especialidad_vuelve_al_dropdown(client, auth_as, seed_users, session):
    auth_as("admin")
    esp = session.exec(
        select(Especialidad).where(Especialidad.nombre == "Oftalmología")
    ).first()
    client.patch(f"/api/v1/especialidades/{esp.id}", json={"activa": False})
    res = client.get("/api/v1/medicos/especialidades")
    assert "Oftalmología" not in res.json()["especialidades"]

    client.patch(f"/api/v1/especialidades/{esp.id}", json={"activa": True})
    res = client.get("/api/v1/medicos/especialidades")
    assert "Oftalmología" in res.json()["especialidades"]


def test_crear_medico_con_especialidad_inactiva_422(client, auth_as, seed_users, session):
    """Una especialidad inactiva no puede asignarse a un médico nuevo."""
    auth_as("admin")
    esp = session.exec(
        select(Especialidad).where(Especialidad.nombre == "Oftalmología")
    ).first()
    esp.activa = False
    session.add(esp)
    session.commit()

    # Creo un usuario médico nuevo y trato de vincularle Oftalmología (inactiva).
    res_u = client.post(
        "/api/v1/usuarios",
        json={
            "nombre": "Dr. Prueba Inactiva",
            "email": "inactiva@test.do",
            "password": TEST_PASSWORD,
            "rol": "medico",
        },
    )
    assert res_u.status_code == 201
    nuevo_id = res_u.json()["id"]

    res = client.post(
        "/api/v1/medicos",
        json={
            "id_usuario": nuevo_id,
            "nombre": "Prueba",
            "especialidad": "Oftalmología",
        },
    )
    assert res.status_code == 422, res.text
    assert "Especialidad inválida" in res.json()["detail"]


# ──────────────── Auditoría ────────────────

def test_auditoria_crear_especialidad(client, auth_as, seed_users, session):
    auth_as("admin")
    res = client.post(
        "/api/v1/especialidades",
        json={"nombre": "Hematología"},
    )
    assert res.status_code == 201
    creada_id = res.json()["id"]

    log = session.exec(
        select(Auditoria).where(
            Auditoria.tabla_afectada == "especialidades",
            Auditoria.id_registro == creada_id,
        )
    ).first()
    assert log is not None
    assert log.accion.value == "CREATE"
    assert "Hematología" in (log.detalle or "")


def test_auditoria_eliminar_especialidad(client, auth_as, seed_users, session):
    auth_as("admin")
    esp = session.exec(
        select(Especialidad).where(Especialidad.nombre == "Radiología y Diagnóstico por Imágenes")
    ).first()
    target_id = esp.id
    res = client.delete(f"/api/v1/especialidades/{target_id}")
    assert res.status_code == 204

    log = session.exec(
        select(Auditoria).where(
            Auditoria.tabla_afectada == "especialidades",
            Auditoria.id_registro == target_id,
            Auditoria.accion == "DELETE",
        )
    ).first()
    assert log is not None


# ──────────────── Sanity check del seed ────────────────

def test_seed_inicial_inserta_18_activas(session):
    """El conftest debe sembrar exactamente 18 especialidades, todas activas."""
    total = session.exec(select(Especialidad)).all()
    assert len(total) == 18
    assert all(e.activa is True for e in total)
