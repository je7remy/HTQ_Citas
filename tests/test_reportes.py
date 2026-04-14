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
