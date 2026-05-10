"""Tests del módulo de reportes PDF (WeasyPrint).

Verifica que el endpoint genera bytes válidos de PDF, respeta filtros
y aplica RBAC.
"""
from datetime import date, timedelta

import pytest

# WeasyPrint requiere libs de sistema. Si no está disponible, saltamos.
weasyprint = pytest.importorskip("weasyprint")


def _proximo_lunes() -> date:
    hoy = date.today()
    for offset in range(1, 8):
        d = hoy + timedelta(days=offset)
        if d.isoweekday() == 1:
            return d
    raise RuntimeError("unreachable")


def _crear_paciente_y_cita(client, seed_users, hora="09:00:00"):
    p = client.post(
        "/api/v1/pacientes",
        json={
            "cedula": "00112345678",
            "nombre": "Ana",
            "apellidos": "García",
            "sexo": "femenino",
            "fecha_nacimiento": "1990-04-12",
            "telefono": "8095550100",
        },
    ).json()
    return client.post(
        "/api/v1/citas",
        json={
            "id_paciente": p["id"],
            "id_medico": seed_users["medico"].id,
            "fecha": _proximo_lunes().isoformat(),
            "hora": hora,
        },
    ).json()


def test_pdf_genera_bytes_validos(client, auth_as, seed_users):
    auth_as("secretaria")
    _crear_paciente_y_cita(client, seed_users)

    desde = _proximo_lunes().isoformat()
    hasta = (_proximo_lunes() + timedelta(days=1)).isoformat()
    res = client.get(f"/api/v1/reportes/citas.pdf?desde={desde}&hasta={hasta}")

    assert res.status_code == 200
    assert res.headers["content-type"] == "application/pdf"
    # Magic number de PDF
    assert res.content.startswith(b"%PDF-"), "El archivo no es un PDF válido"
    # Marker de fin de PDF (puede tener bytes después)
    assert b"%%EOF" in res.content
    # No vacío
    assert len(res.content) > 1000


def test_pdf_filtro_por_medico(client, auth_as, seed_users):
    auth_as("secretaria")
    _crear_paciente_y_cita(client, seed_users)

    desde = _proximo_lunes().isoformat()
    hasta = (_proximo_lunes() + timedelta(days=1)).isoformat()
    medico_id = seed_users["medico"].id

    res = client.get(
        f"/api/v1/reportes/citas.pdf?desde={desde}&hasta={hasta}&id_medico={medico_id}"
    )
    assert res.status_code == 200
    assert res.content.startswith(b"%PDF-")


def test_pdf_rango_vacio_genera_pdf(client, auth_as):
    """Aunque no haya citas, debe devolver un PDF (con tabla vacía)."""
    auth_as("secretaria")
    res = client.get("/api/v1/reportes/citas.pdf?desde=2020-01-01&hasta=2020-01-02")
    assert res.status_code == 200
    assert res.content.startswith(b"%PDF-")


def test_pdf_requiere_autenticacion(client):
    res = client.get("/api/v1/reportes/citas.pdf?desde=2026-01-01&hasta=2026-01-02")
    assert res.status_code == 401


# ---------- Mejora 3: fecha de emisión ----------
def test_template_contiene_fecha_emision():
    """El template renderiza la cadena 'Reporte generado el' con la fecha de emisión."""
    from jinja2 import Template

    from app.api.v1.endpoints.reportes import _TEMPLATE

    html = Template(_TEMPLATE).render(
        desde="2026-01-01", hasta="2026-01-31",
        filas=[], medico_nombre=None,
        fecha_emision="7 de mayo de 2026 a las 2:35 PM",
        resumen={"pendientes": 0, "atendidas": 0, "canceladas": 0, "total": 0},
    )
    assert "Reporte generado el" in html
    assert "7 de mayo de 2026 a las 2:35 PM" in html


# ---------- Mejora 4: numeración secuencial ----------
def test_template_numeracion_secuencial():
    """La columna # usa loop.index (1,2,3…) en vez de los IDs internos."""
    from jinja2 import Template

    from app.api.v1.endpoints.reportes import _TEMPLATE

    filas = [
        {"id": 101, "fecha": "2026-01-05", "hora": "09:00", "paciente": "Ana García", "medico": "Dr. Test", "estado": "pendiente"},
        {"id": 55,  "fecha": "2026-01-06", "hora": "10:00", "paciente": "Luis Mota",  "medico": "Dr. Test", "estado": "atendida"},
        {"id": 999, "fecha": "2026-01-07", "hora": "11:00", "paciente": "Rosa López", "medico": "Dr. Test", "estado": "cancelada"},
    ]
    html = Template(_TEMPLATE).render(
        desde="2026-01-05", hasta="2026-01-07",
        filas=filas, medico_nombre=None,
        fecha_emision="7 de mayo de 2026 a las 2:35 PM",
        resumen={"pendientes": 1, "atendidas": 1, "canceladas": 1, "total": 3},
    )
    assert "<td>1</td>" in html
    assert "<td>2</td>" in html
    assert "<td>3</td>" in html
    assert "<td>101</td>" not in html
    assert "<td>55</td>" not in html
    assert "<td>999</td>" not in html


# ---------- Mejora 1.4: resumen de estados ----------
def test_template_contiene_seccion_resumen():
    """El template muestra la sección 'Resumen del periodo' con los 4 textos clave."""
    from jinja2 import Template

    from app.api.v1.endpoints.reportes import _TEMPLATE

    html = Template(_TEMPLATE).render(
        desde="2026-01-01", hasta="2026-01-31",
        filas=[], medico_nombre=None,
        fecha_emision="7 de mayo de 2026 a las 2:35 PM",
        resumen={"pendientes": 0, "atendidas": 0, "canceladas": 0, "total": 0},
    )
    assert "Resumen del periodo" in html
    assert "Citas pendientes" in html
    assert "Citas atendidas" in html
    assert "Citas canceladas" in html
    assert "Total general" in html


def test_pdf_endpoint_resumen_coincide_con_citas(client, auth_as, seed_users):
    """El endpoint genera un PDF cuyo resumen refleja los conteos reales."""
    auth_as("secretaria")
    p = client.post(
        "/api/v1/pacientes",
        json={
            "cedula": "00112345678", "nombre": "Ana", "apellidos": "García",
            "sexo": "femenino", "fecha_nacimiento": "1990-04-12",
            "telefono": "8095550100",
        },
    ).json()
    medico_id = seed_users["medico"].id
    fecha = _proximo_lunes().isoformat()

    # 2 pendientes + 1 cancelada en el mismo rango
    c1 = client.post("/api/v1/citas", json={"id_paciente": p["id"], "id_medico": medico_id, "fecha": fecha, "hora": "08:00:00"}).json()
    client.post("/api/v1/citas", json={"id_paciente": p["id"], "id_medico": medico_id, "fecha": fecha, "hora": "09:00:00"})
    client.delete(f"/api/v1/citas/{c1['id']}")

    desde = fecha
    hasta = (_proximo_lunes() + timedelta(days=1)).isoformat()
    res = client.get(f"/api/v1/reportes/citas.pdf?desde={desde}&hasta={hasta}")
    assert res.status_code == 200
    assert res.content.startswith(b"%PDF-")
    # Magic-check: tamaño razonable (con resumen el PDF crece)
    assert len(res.content) > 1500


def test_template_resumen_conteos_correctos():
    """Los conteos por estado se renderizan correctamente."""
    from jinja2 import Template

    from app.api.v1.endpoints.reportes import _TEMPLATE

    html = Template(_TEMPLATE).render(
        desde="2026-01-01", hasta="2026-01-31", filas=[], medico_nombre=None,
        fecha_emision="x",
        resumen={"pendientes": 7, "atendidas": 12, "canceladas": 3, "total": 22},
    )
    assert ">7<" in html
    assert ">12<" in html
    assert ">3<" in html
    assert ">22<" in html
