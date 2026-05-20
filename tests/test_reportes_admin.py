"""Tests para el módulo de reportes administrativos (usuarios y médicos).

Cubre RBAC, estructura JSON, integridad de los PDFs, cálculo de tasas
y registro de auditoría al generar los reportes.
"""
from datetime import date, time, timedelta

import pytest
from sqlmodel import Session, select

from app.core.security import hash_password
from app.models import (
    AccionAuditoria,
    Auditoria,
    Cita,
    Consulta,
    EstadoCita,
    Medico,
    RolUsuario,
    Usuario,
)
from tests.conftest import TEST_PASSWORD

weasyprint = pytest.importorskip("weasyprint")


def _pasado_lunes() -> date:
    hoy = date.today()
    for offset in range(1, 15):
        d = hoy - timedelta(days=offset)
        if d.isoweekday() == 1:
            return d
    raise RuntimeError("unreachable")


# ────────────── A) Resumen JSON ──────────────
def test_reporte_usuarios_resumen_solo_admin(client, auth_as, seed_users):
    auth_as("secretaria")
    res = client.get("/api/v1/reportes/usuarios/resumen")
    assert res.status_code == 403

    auth_as("medico")
    res = client.get("/api/v1/reportes/usuarios/resumen")
    assert res.status_code == 403

    auth_as("admin")
    res = client.get("/api/v1/reportes/usuarios/resumen")
    assert res.status_code == 200


def test_reporte_usuarios_resumen_devuelve_estructura_correcta(
    client, auth_as, seed_users
):
    auth_as("admin")
    res = client.get("/api/v1/reportes/usuarios/resumen")
    assert res.status_code == 200
    body = res.json()

    assert set(body.keys()) >= {"total_usuarios", "por_rol", "fecha_generacion"}
    assert body["total_usuarios"] == 3  # seed: admin + secretaria + medico

    por_rol = body["por_rol"]
    assert set(por_rol.keys()) == {"admin", "secretaria", "medico"}

    # Admin y médico: keys masculinas
    assert por_rol["admin"] == {"total": 1, "activos": 1, "inactivos": 0}
    assert por_rol["medico"] == {"total": 1, "activos": 1, "inactivos": 0}
    # Secretaria: keys femeninas
    assert por_rol["secretaria"] == {"total": 1, "activas": 1, "inactivas": 0}


def test_reporte_usuarios_resumen_cuenta_inactivos(
    client, auth_as, seed_users, session: Session
):
    """Un médico inactivo debe contarse en la columna 'inactivos'."""
    medico_user = seed_users["medico_user"]
    medico_user.activo = False
    session.add(medico_user)
    session.commit()

    auth_as("admin")
    body = client.get("/api/v1/reportes/usuarios/resumen").json()
    assert body["por_rol"]["medico"] == {"total": 1, "activos": 0, "inactivos": 1}


# ────────────── B) PDF de usuarios ──────────────
def test_reporte_usuarios_pdf_genera_archivo_no_vacio(client, auth_as, seed_users):
    auth_as("admin")
    res = client.get("/api/v1/reportes/usuarios/pdf")
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/pdf"
    assert res.content.startswith(b"%PDF-")
    assert b"%%EOF" in res.content
    assert len(res.content) > 1500


def test_reporte_usuarios_pdf_solo_admin(client, auth_as, seed_users):
    auth_as("secretaria")
    assert client.get("/api/v1/reportes/usuarios/pdf").status_code == 403
    auth_as("medico")
    assert client.get("/api/v1/reportes/usuarios/pdf").status_code == 403


# ────────────── C) Detalle de médicos ──────────────
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


def test_reporte_medicos_detalle_calcula_tasas_correctamente(
    client, auth_as, seed_users, session: Session
):
    """Crea 4 citas para el médico: 2 atendidas, 1 cancelada, 1 pendiente.
    Verifica que el endpoint reporta las tasas correctas (50% / 25%).
    """
    auth_as("secretaria")
    paciente_id = _crear_paciente(client)
    medico_id = seed_users["medico"].id
    secretaria_id = seed_users["secretaria"].id

    # 4 citas pasadas insertadas directamente en BD (saltando validaciones de POST)
    horas = [time(8, 0), time(9, 0), time(10, 0), time(11, 0)]
    citas = []
    for h in horas:
        c = Cita(
            id_paciente=paciente_id,
            id_medico=medico_id,
            fecha=_pasado_lunes(),
            hora=h,
            id_secretaria=secretaria_id,
        )
        session.add(c)
        citas.append(c)
    session.commit()
    for c in citas:
        session.refresh(c)

    # 2 atendidas (con consulta), 1 cancelada, 1 pendiente
    citas[0].estado = EstadoCita.atendida
    citas[1].estado = EstadoCita.atendida
    citas[2].estado = EstadoCita.cancelada
    # citas[3] queda pendiente
    for c in citas:
        session.add(c)
    # Consultas (sólo para las atendidas)
    session.add(Consulta(id_cita=citas[0].id, condicion_principal="Dx 1"))
    session.add(Consulta(id_cita=citas[1].id, condicion_principal="Dx 2"))
    session.commit()

    auth_as("admin")
    res = client.get("/api/v1/reportes/medicos/detalle")
    assert res.status_code == 200
    body = res.json()
    assert body["total_medicos"] == 1
    m = body["medicos"][0]
    assert m["total_citas"] == 4
    assert m["citas_atendidas"] == 2
    assert m["citas_canceladas"] == 1
    assert m["citas_pendientes"] == 1
    assert m["total_consultas"] == 2
    assert m["tasa_atendidas"] == 50.0
    assert m["tasa_canceladas"] == 25.0
    assert m["dias_disponibilidad"] == 5  # L-V configurado en seed


def test_reporte_medicos_detalle_solo_admin(client, auth_as, seed_users):
    auth_as("secretaria")
    assert client.get("/api/v1/reportes/medicos/detalle").status_code == 403
    auth_as("medico")
    assert client.get("/api/v1/reportes/medicos/detalle").status_code == 403


# ────────────── D) PDF de médicos ──────────────
def test_reporte_medicos_pdf_incluye_todos_los_medicos_activos(
    client, auth_as, seed_users, session: Session
):
    """Crea 2 médicos adicionales (1 activo, 1 inactivo) y valida que sólo
    los activos aparezcan en el detalle JSON (y por extensión en el PDF)."""
    user_b = Usuario(
        nombre="Dr. Bravo",
        email="bravo@test.do",
        password_hash=hash_password(TEST_PASSWORD),
        rol=RolUsuario.medico,
    )
    user_c = Usuario(
        nombre="Dr. Charlie",
        email="charlie@test.do",
        password_hash=hash_password(TEST_PASSWORD),
        rol=RolUsuario.medico,
    )
    session.add_all([user_b, user_c])
    session.flush()
    medico_b = Medico(
        id_usuario=user_b.id, nombre="Bravo", especialidad="Medicina Interna"
    )
    medico_c = Medico(
        id_usuario=user_c.id,
        nombre="Charlie",
        especialidad="Cirugía General",
        activo=False,
    )
    session.add_all([medico_b, medico_c])
    session.commit()

    auth_as("admin")

    # JSON: 2 activos (seed + bravo), no charlie (inactivo)
    body = client.get("/api/v1/reportes/medicos/detalle").json()
    nombres = {m["nombre"] for m in body["medicos"]}
    assert nombres == {"Dr. Test", "Bravo"}
    assert body["total_medicos"] == 2

    # PDF: válido y no vacío
    res = client.get("/api/v1/reportes/medicos/pdf")
    assert res.status_code == 200
    assert res.content.startswith(b"%PDF-")
    assert b"%%EOF" in res.content
    assert len(res.content) > 1500


def test_reporte_medicos_pdf_solo_admin(client, auth_as, seed_users):
    auth_as("secretaria")
    assert client.get("/api/v1/reportes/medicos/pdf").status_code == 403


# ────────────── E) Auditoría ──────────────
def test_reporte_genera_registro_auditoria(client, auth_as, seed_users, session):
    """Generar un PDF de usuarios o médicos deja un registro en auditoría."""
    auth_as("admin")

    res = client.get("/api/v1/reportes/usuarios/pdf")
    assert res.status_code == 200

    res = client.get("/api/v1/reportes/medicos/pdf")
    assert res.status_code == 200

    logs = session.exec(
        select(Auditoria).where(
            Auditoria.tabla_afectada == "reportes",
            Auditoria.accion == AccionAuditoria.CREATE,
        )
    ).all()
    detalles = [log.detalle for log in logs]
    assert any("usuarios" in (d or "") for d in detalles)
    assert any("medicos" in (d or "") for d in detalles)
    # El nombre del usuario quedó denormalizado
    assert all(log.nombre_usuario == seed_users["admin"].nombre for log in logs)


# ────────────── F) Trazabilidad: "Generado por" ──────────────
def test_template_usuarios_contiene_generado_por():
    from jinja2 import Template

    from app.api.v1.endpoints.reportes_admin import _BASE_CSS, _USUARIOS_TEMPLATE

    html = Template(_USUARIOS_TEMPLATE).render(
        base_css=_BASE_CSS,
        fecha_emision="x",
        generado_por="Admin Test",
        resumen_rol=[],
        usuarios_por_rol=[],
        totales={"admin": 0, "secretaria": 0, "medico": 0, "total": 0},
        top_especialidades=[],
        top_secretaria=None,
        top_medico_consultas=None,
    )
    assert "Generado por:" in html
    assert "Admin Test" in html


def test_template_medicos_contiene_generado_por():
    from jinja2 import Template

    from app.api.v1.endpoints.reportes_admin import _BASE_CSS, _MEDICOS_TEMPLATE

    html = Template(_MEDICOS_TEMPLATE).render(
        base_css=_BASE_CSS,
        fecha_emision="x",
        generado_por="Admin Test",
        medicos=[],
        resumen={"total_medicos": 0, "total_citas": 0, "total_consultas": 0, "promedio_citas": 0.0},
    )
    assert "Generado por:" in html
    assert "Admin Test" in html


@pytest.mark.requires_weasyprint
def test_pdf_usuarios_refleja_dos_admin_distintos(
    client, auth_as, seed_users, session
):
    """Dos admin distintos generan el mismo reporte → cada PDF lleva su nombre."""
    admin_b = Usuario(
        nombre="Admin Bravo",
        email="adminb@test.do",
        password_hash=hash_password(TEST_PASSWORD),
        rol=RolUsuario.admin,
    )
    session.add(admin_b)
    session.commit()
    session.refresh(admin_b)

    auth_as("admin")
    pdf_a = client.get("/api/v1/reportes/usuarios/pdf").content

    # Forzamos al cliente como admin_b sin pasar por seed_users
    from app.api.deps import get_current_user
    from app.main import app

    app.dependency_overrides[get_current_user] = lambda: admin_b
    pdf_b = client.get("/api/v1/reportes/usuarios/pdf").content

    assert seed_users["admin"].nombre.encode("utf-8") in pdf_a
    assert admin_b.nombre.encode("utf-8") not in pdf_a
    assert admin_b.nombre.encode("utf-8") in pdf_b


@pytest.mark.requires_weasyprint
def test_pdf_medicos_contiene_nombre_admin(client, auth_as, seed_users):
    auth_as("admin")
    res = client.get("/api/v1/reportes/medicos/pdf")
    assert res.status_code == 200
    assert seed_users["admin"].nombre.encode("utf-8") in res.content
