"""Tests de la pantalla Agenda del Día de la secretaria.

Cubre:
- /api/v1/citas/agenda-extendida (RBAC, filtros y conteos)
- /api/v1/medicos/buscar (autocomplete + exclusión de inactivos)
- /api/v1/reportes/agenda/pdf y /excel
"""
from datetime import date, timedelta

import pytest

from app.core.security import hash_password
from app.models import Horario, Medico, RolUsuario, Usuario
from tests.conftest import TEST_PASSWORD  # noqa: F401  (asegura constante única)


def _proximo_dia_semana(target_iso: int) -> date:
    hoy = date.today()
    for offset in range(1, 15):
        d = hoy + timedelta(days=offset)
        if d.isoweekday() == target_iso:
            return d
    raise RuntimeError("unreachable")


def _crear_paciente(client, cedula="00112345678", nombre="Ana", apellidos="García"):
    res = client.post(
        "/api/v1/pacientes",
        json={
            "cedula": cedula,
            "nombre": nombre,
            "apellidos": apellidos,
            "sexo": "femenino",
            "fecha_nacimiento": "1990-04-12",
            "telefono": "8095550100",
        },
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


def _crear_cita(client, paciente_id, medico_id, fecha_iso, hora):
    res = client.post(
        "/api/v1/citas",
        json={
            "id_paciente": paciente_id,
            "id_medico": medico_id,
            "fecha": fecha_iso,
            "hora": hora,
        },
    )
    assert res.status_code == 201, res.text
    return res.json()


def _crear_segundo_medico(session, *, especialidad="Medicina Interna", activo=True):
    """Crea otro médico (con horario L-V 8-12) para pruebas con múltiples médicos."""
    u = Usuario(
        nombre="Dr. Otro",
        email=f"otro_{activo}_{especialidad}@test.do",
        password_hash=hash_password("test-password-fixture-only"),
        rol=RolUsuario.medico,
    )
    session.add(u)
    session.flush()
    m = Medico(
        id_usuario=u.id,
        nombre="Otro Médico",
        especialidad=especialidad,
        activo=activo,
    )
    session.add(m)
    session.flush()
    if activo:
        for dia in range(1, 6):
            session.add(
                Horario(
                    id_medico=m.id,
                    dia_semana=dia,
                    hora_inicio=__import__("datetime").time(8, 0),
                    hora_fin=__import__("datetime").time(12, 0),
                )
            )
    session.commit()
    return m


# ───────────────────── 1. RBAC ─────────────────────
def test_agenda_extendida_solo_secretaria_y_admin(client, auth_as, seed_users):
    # medico → 403
    auth_as("medico")
    res = client.get("/api/v1/citas/agenda-extendida")
    assert res.status_code == 403

    # secretaria → 200
    auth_as("secretaria")
    res = client.get("/api/v1/citas/agenda-extendida")
    assert res.status_code == 200

    # admin → 200
    auth_as("admin")
    res = client.get("/api/v1/citas/agenda-extendida")
    assert res.status_code == 200


# ───────────────────── 2. Filtro por médico ─────────────────────
def test_agenda_extendida_filtra_por_medico_correctamente(client, auth_as, seed_users, session):
    auth_as("secretaria")
    paciente_id = _crear_paciente(client)
    medico_a = seed_users["medico"].id
    medico_b = _crear_segundo_medico(session).id
    fecha = _proximo_dia_semana(1).isoformat()

    _crear_cita(client, paciente_id, medico_a, fecha, "08:00:00")
    _crear_cita(client, paciente_id, medico_a, fecha, "09:00:00")
    _crear_cita(client, paciente_id, medico_b, fecha, "10:00:00")

    res = client.get(f"/api/v1/citas/agenda-extendida?id_medico={medico_a}")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 2
    assert all(c["id_medico"] == medico_a for c in data["citas"])


# ───────────────────── 3. Filtro por rango de fechas ─────────────────────
def test_agenda_extendida_filtra_por_rango_fechas(client, auth_as, seed_users):
    auth_as("secretaria")
    paciente_id = _crear_paciente(client)
    medico_id = seed_users["medico"].id
    lunes = _proximo_dia_semana(1)
    miercoles = _proximo_dia_semana(3)

    _crear_cita(client, paciente_id, medico_id, lunes.isoformat(), "08:00:00")
    _crear_cita(client, paciente_id, medico_id, miercoles.isoformat(), "09:00:00")

    # Solo el lunes
    res = client.get(
        f"/api/v1/citas/agenda-extendida?fecha_desde={lunes.isoformat()}"
        f"&fecha_hasta={lunes.isoformat()}"
    )
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert data["citas"][0]["fecha"] == lunes.isoformat()

    # Rango completo lunes..miércoles
    res = client.get(
        f"/api/v1/citas/agenda-extendida?fecha_desde={lunes.isoformat()}"
        f"&fecha_hasta={miercoles.isoformat()}"
    )
    assert res.json()["total"] == 2


# ───────────────────── 4. Conteos por estado ─────────────────────
def test_agenda_extendida_calcula_conteos_correctos(client, auth_as, seed_users):
    auth_as("secretaria")
    paciente_id = _crear_paciente(client)
    medico_id = seed_users["medico"].id
    fecha = _proximo_dia_semana(2).isoformat()

    # 2 pendientes + 1 que cancelaremos
    c1 = _crear_cita(client, paciente_id, medico_id, fecha, "08:00:00")
    _crear_cita(client, paciente_id, medico_id, fecha, "09:00:00")
    c3 = _crear_cita(client, paciente_id, medico_id, fecha, "10:00:00")
    client.delete(f"/api/v1/citas/{c3['id']}")

    # Cambia c1 a atendida vía PATCH
    client.patch(f"/api/v1/citas/{c1['id']}", json={"estado": "atendida"})

    res = client.get(f"/api/v1/citas/agenda-extendida?fecha_desde={fecha}&fecha_hasta={fecha}")
    data = res.json()
    assert data["total"] == 3
    assert data["pendientes"] == 1
    assert data["atendidas"] == 1
    assert data["canceladas"] == 1


# ───────────────────── 5. Búsqueda de médicos — coincidencias parciales ─────────────────────
def test_medicos_buscar_devuelve_coincidencias_parciales(client, auth_as, seed_users, session):
    auth_as("secretaria")
    # seed_users crea un médico "Dr. Test" (sin prefijo en BD: queda "Test")
    # Añadimos un segundo médico para tener un caso de "no coincide".
    _crear_segundo_medico(session, especialidad="Cirugía General")

    res = client.get("/api/v1/medicos/buscar?q=test")
    assert res.status_code == 200
    nombres = [m["nombre"].lower() for m in res.json()]
    assert any("test" in n for n in nombres)

    res = client.get("/api/v1/medicos/buscar?q=otro")
    assert res.status_code == 200
    assert all("otro" in m["nombre"].lower() for m in res.json())


# ───────────────────── 6. Búsqueda excluye inactivos ─────────────────────
def test_medicos_buscar_excluye_inactivos_por_default(client, auth_as, seed_users, session):
    auth_as("secretaria")
    # Crear un médico inactivo cuyo nombre contiene "Test"
    u = Usuario(
        nombre="Inactivo Test",
        email="inactivo@test.do",
        password_hash=hash_password("test-password-fixture-only"),
        rol=RolUsuario.medico,
    )
    session.add(u)
    session.flush()
    m = Medico(id_usuario=u.id, nombre="Test Inactivo", especialidad="Anestesiología", activo=False)
    session.add(m)
    session.commit()

    # Por defecto excluye inactivos
    res = client.get("/api/v1/medicos/buscar?q=inactivo")
    assert res.status_code == 200
    assert res.json() == []

    # Con flag explícito los incluye
    res = client.get("/api/v1/medicos/buscar?q=inactivo&incluir_inactivos=true")
    assert res.status_code == 200
    assert len(res.json()) == 1
    assert res.json()[0]["nombre"] == "Test Inactivo"


# ───────────────────── 7. Reporte PDF respeta filtros ─────────────────────
def test_reporte_agenda_pdf_respeta_filtros(client, auth_as, seed_users):
    pytest.importorskip("weasyprint")
    auth_as("secretaria")
    paciente_id = _crear_paciente(client)
    medico_id = seed_users["medico"].id
    fecha = _proximo_dia_semana(2).isoformat()
    _crear_cita(client, paciente_id, medico_id, fecha, "08:00:00")

    res = client.get(
        f"/api/v1/reportes/agenda/pdf?fecha_desde={fecha}&fecha_hasta={fecha}"
        f"&id_medico={medico_id}&estado=pendiente"
    )
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/pdf"
    assert res.content.startswith(b"%PDF-")
    assert b"%%EOF" in res.content
    assert len(res.content) > 1000

    # RBAC: el médico no puede acceder al reporte de agenda
    auth_as("medico")
    res2 = client.get(
        f"/api/v1/reportes/agenda/pdf?fecha_desde={fecha}&fecha_hasta={fecha}"
    )
    assert res2.status_code == 403


# ───────────────────── 8. Reporte Excel válido ─────────────────────
def test_reporte_agenda_excel_genera_archivo_valido(client, auth_as, seed_users):
    openpyxl = pytest.importorskip("openpyxl")
    auth_as("secretaria")
    paciente_id = _crear_paciente(client)
    medico_id = seed_users["medico"].id
    fecha = _proximo_dia_semana(2).isoformat()
    _crear_cita(client, paciente_id, medico_id, fecha, "08:00:00")
    _crear_cita(client, paciente_id, medico_id, fecha, "09:00:00")

    res = client.get(
        f"/api/v1/reportes/agenda/excel?fecha_desde={fecha}&fecha_hasta={fecha}"
    )
    assert res.status_code == 200
    assert "spreadsheetml" in res.headers["content-type"]

    # Es un .xlsx válido (zip + sheets)
    from io import BytesIO
    wb = openpyxl.load_workbook(BytesIO(res.content))
    ws = wb.active
    assert ws.title == "Agenda"
    # Cabecera SGCM presente en la primera celda
    assert "SGCM" in str(ws["A1"].value)
    # Filtros y resumen
    todas_celdas = " ".join(str(c.value) for row in ws.iter_rows() for c in row if c.value)
    assert "Filtros" in todas_celdas
    assert "Resumen" in todas_celdas
    # Al menos las 2 filas de citas
    assert "Ana García" in todas_celdas


# ───────────────────── Extras: datetime ISO en filtros ─────────────────────
def test_agenda_extendida_acepta_datetime_iso(client, auth_as, seed_users):
    auth_as("secretaria")
    paciente_id = _crear_paciente(client)
    medico_id = seed_users["medico"].id
    fecha = _proximo_dia_semana(1)
    _crear_cita(client, paciente_id, medico_id, fecha.isoformat(), "08:00:00")

    res = client.get(
        f"/api/v1/citas/agenda-extendida"
        f"?fecha_desde={fecha.isoformat()}T00:00:00"
        f"&fecha_hasta={fecha.isoformat()}T23:59:59"
    )
    assert res.status_code == 200
    assert res.json()["total"] == 1
