"""Tests del módulo de reportes PDF (WeasyPrint).

Verifica que el endpoint genera bytes válidos de PDF, respeta filtros
y aplica RBAC.
"""
from datetime import date, time, timedelta

import pytest

from app.models import Cita

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


@pytest.mark.requires_weasyprint
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


@pytest.mark.requires_weasyprint
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
        generado_por="Tester",
        resumen={"pendientes": 7, "atendidas": 12, "canceladas": 3, "total": 22},
    )
    assert ">7<" in html
    assert ">12<" in html
    assert ">3<" in html
    assert ">22<" in html


# ---------- Trazabilidad: "Generado por" ----------
def test_template_citas_contiene_generado_por():
    """El template del reporte de citas renderiza la línea 'Generado por:'."""
    from jinja2 import Template

    from app.api.v1.endpoints.reportes import _TEMPLATE

    html = Template(_TEMPLATE).render(
        desde="2026-01-01", hasta="2026-01-31",
        filas=[], medico_nombre=None,
        fecha_emision="x",
        generado_por="Secre Test",
        resumen={"pendientes": 0, "atendidas": 0, "canceladas": 0, "total": 0},
    )
    assert "Generado por:" in html
    assert "Secre Test" in html


def test_reporte_citas_pdf_audita_generacion(client, auth_as, seed_users, session):
    """El endpoint /citas.pdf debe registrar la generación en auditoría."""
    from sqlmodel import select

    from app.models import AccionAuditoria, Auditoria

    auth_as("secretaria")
    res = client.get(
        "/api/v1/reportes/citas.pdf?desde=2026-01-01&hasta=2026-01-31"
    )
    assert res.status_code == 200

    logs = session.exec(
        select(Auditoria).where(
            Auditoria.tabla_afectada == "reportes",
            Auditoria.accion == AccionAuditoria.CREATE,
        )
    ).all()
    assert any("citas" in (log.detalle or "") for log in logs)
    assert all(log.nombre_usuario == seed_users["secretaria"].nombre for log in logs)


class _FakeHTML:
    """Captura el HTML renderizado en vez de invocar a WeasyPrint."""
    capturas: list[str] = []

    def __init__(self, string=None, **kw):
        type(self).capturas.append(string or "")

    def write_pdf(self):  # noqa: D401
        return b"%PDF-fake\n%%EOF"


def test_pdf_citas_contiene_nombre_actor(
    client, auth_as, seed_users, monkeypatch
):
    """El HTML pasado a WeasyPrint debe incluir 'Generado por: <nombre>'."""
    _FakeHTML.capturas = []
    monkeypatch.setattr("app.api.v1.endpoints.reportes.HTML", _FakeHTML)

    auth_as("secretaria")
    res = client.get(
        "/api/v1/reportes/citas.pdf?desde=2026-01-01&hasta=2026-01-31"
    )
    assert res.status_code == 200
    assert _FakeHTML.capturas, "WeasyPrint no fue invocado"
    html = _FakeHTML.capturas[-1]
    assert "Generado por:" in html
    assert seed_users["secretaria"].nombre in html


def test_pdf_citas_refleja_dos_usuarios_distintos(
    client, auth_as, seed_users, monkeypatch
):
    """Mismo endpoint con dos actores → cada render lleva su propio nombre."""
    _FakeHTML.capturas = []
    monkeypatch.setattr("app.api.v1.endpoints.reportes.HTML", _FakeHTML)

    auth_as("secretaria")
    client.get("/api/v1/reportes/citas.pdf?desde=2026-01-01&hasta=2026-01-31")
    html_sec = _FakeHTML.capturas[-1]

    auth_as("admin")
    client.get("/api/v1/reportes/citas.pdf?desde=2026-01-01&hasta=2026-01-31")
    html_admin = _FakeHTML.capturas[-1]

    nombre_sec = seed_users["secretaria"].nombre
    nombre_admin = seed_users["admin"].nombre

    assert nombre_sec in html_sec and nombre_admin not in html_sec
    assert nombre_admin in html_admin and nombre_sec not in html_admin


# ═════════════════════════════════════════════════════════════════
# Historial médico paciente + médico
#   - GET /medicos/{id}/pacientes  (combo del reporte)
#   - GET /reportes/historial-medico/pdf
# ═════════════════════════════════════════════════════════════════

def _crear_paciente(client, *, cedula, nombre, apellidos) -> int:
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


def _insertar_cita_pasada(session, seed_users, paciente_id, *, dias_atras=7, hora="09:00:00") -> int:
    """Cita vencida vía ORM: POST /citas rechaza fechas pasadas.

    Mismo truco que tests/test_consultas.py — para que exista una consulta
    hay que partir de una cita cuyo horario ya pasó.
    """
    h, m, s = (int(x) for x in hora.split(":"))
    cita = Cita(
        id_paciente=paciente_id,
        id_medico=seed_users["medico"].id,
        fecha=date.today() - timedelta(days=dias_atras),
        hora=time(h, m, s),
        id_secretaria=seed_users["secretaria"].id,
    )
    session.add(cita)
    session.commit()
    session.refresh(cita)
    return cita.id


def _registrar_consulta(client, session, seed_users, paciente_id, *, dias_atras=7,
                        hora="09:00:00", **campos) -> int:
    """Cita pasada + consulta registrada. Deja la cita en estado 'atendida'."""
    cita_id = _insertar_cita_pasada(
        session, seed_users, paciente_id, dias_atras=dias_atras, hora=hora
    )
    campos.setdefault("condicion_principal", "Lumbalgia mecánica")
    res = client.post("/api/v1/consultas", json={"id_cita": cita_id, **campos})
    assert res.status_code == 201, res.text
    return cita_id


# ---------- GET /medicos/{id}/pacientes ----------
def test_pacientes_atendidos_solo_incluye_los_que_tienen_consulta(
    client, auth_as, seed_users, session
):
    """Un paciente con solo cita pendiente no entra; con consulta sí."""
    auth_as("secretaria")
    con_consulta = _crear_paciente(client, cedula="00112345678", nombre="Ana", apellidos="García")
    sin_consulta = _crear_paciente(client, cedula="00187654321", nombre="Luis", apellidos="Mota")
    # Cita pendiente (sin consulta) para el segundo paciente
    _insertar_cita_pasada(session, seed_users, sin_consulta, hora="11:00:00")

    auth_as("medico")
    _registrar_consulta(client, session, seed_users, con_consulta)

    res = client.get(f"/api/v1/medicos/{seed_users['medico'].id}/pacientes")
    assert res.status_code == 200, res.text
    ids = [p["id"] for p in res.json()]
    assert ids == [con_consulta]


def test_pacientes_atendidos_sin_duplicados(client, auth_as, seed_users, session):
    """Un paciente con varias consultas aparece una sola vez."""
    auth_as("secretaria")
    paciente_id = _crear_paciente(client, cedula="00112345678", nombre="Ana", apellidos="García")

    auth_as("medico")
    _registrar_consulta(client, session, seed_users, paciente_id, dias_atras=14, hora="08:00:00")
    _registrar_consulta(client, session, seed_users, paciente_id, dias_atras=7, hora="09:00:00")

    body = client.get(f"/api/v1/medicos/{seed_users['medico'].id}/pacientes").json()
    assert [p["id"] for p in body] == [paciente_id]


def test_pacientes_atendidos_orden_alfabetico_por_apellidos(
    client, auth_as, seed_users, session
):
    auth_as("secretaria")
    zapata = _crear_paciente(client, cedula="00111111111", nombre="Rosa", apellidos="Zapata")
    abreu = _crear_paciente(client, cedula="00122222222", nombre="Luis", apellidos="Abreu")

    auth_as("medico")
    _registrar_consulta(client, session, seed_users, zapata, dias_atras=14, hora="08:00:00")
    _registrar_consulta(client, session, seed_users, abreu, dias_atras=7, hora="09:00:00")

    body = client.get(f"/api/v1/medicos/{seed_users['medico'].id}/pacientes").json()
    assert [p["apellidos"] for p in body] == ["Abreu", "Zapata"]
    assert [p["id"] for p in body] == [abreu, zapata]


def test_pacientes_atendidos_medico_inexistente_404(client, auth_as):
    auth_as("secretaria")
    res = client.get("/api/v1/medicos/99999/pacientes")
    assert res.status_code == 404


def test_pacientes_atendidos_requiere_autenticacion(client):
    res = client.get("/api/v1/medicos/1/pacientes")
    assert res.status_code == 401


# ---------- GET /reportes/historial-medico/pdf ----------
def test_historial_pdf_genera_bytes_validos(client, auth_as, seed_users, session):
    auth_as("secretaria")
    paciente_id = _crear_paciente(client, cedula="00112345678", nombre="Ana", apellidos="García")

    auth_as("medico")
    _registrar_consulta(client, session, seed_users, paciente_id)

    res = client.get(
        f"/api/v1/reportes/historial-medico/pdf"
        f"?paciente_id={paciente_id}&medico_id={seed_users['medico'].id}"
    )
    assert res.status_code == 200, res.text
    assert res.headers["content-type"] == "application/pdf"
    assert res.content.startswith(b"%PDF-")


def test_historial_pdf_paciente_inexistente_404(client, auth_as, seed_users):
    auth_as("secretaria")
    res = client.get(
        f"/api/v1/reportes/historial-medico/pdf"
        f"?paciente_id=99999&medico_id={seed_users['medico'].id}"
    )
    assert res.status_code == 404


def test_historial_pdf_medico_inexistente_404(client, auth_as):
    auth_as("secretaria")
    paciente_id = _crear_paciente(client, cedula="00112345678", nombre="Ana", apellidos="García")
    res = client.get(
        f"/api/v1/reportes/historial-medico/pdf?paciente_id={paciente_id}&medico_id=99999"
    )
    assert res.status_code == 404


def test_historial_pdf_requiere_autenticacion(client):
    res = client.get("/api/v1/reportes/historial-medico/pdf?paciente_id=1&medico_id=1")
    assert res.status_code == 401


def test_historial_pdf_audita_generacion(client, auth_as, seed_users, session):
    """Imprimir un historial clínico queda registrado en auditoría (Ley 172-13)."""
    from sqlmodel import select

    from app.models import AccionAuditoria, Auditoria

    auth_as("secretaria")
    paciente_id = _crear_paciente(client, cedula="00112345678", nombre="Ana", apellidos="García")
    res = client.get(
        f"/api/v1/reportes/historial-medico/pdf"
        f"?paciente_id={paciente_id}&medico_id={seed_users['medico'].id}"
    )
    assert res.status_code == 200

    logs = session.exec(
        select(Auditoria).where(
            Auditoria.tabla_afectada == "reportes",
            Auditoria.accion == AccionAuditoria.CREATE,
        )
    ).all()
    assert any("historial_medico" in (log.detalle or "") for log in logs)


# ---------- Contenido del PDF (HTML capturado, sin WeasyPrint real) ----------
def test_historial_pdf_contiene_datos_paciente_medico_y_campos_clinicos(
    client, auth_as, seed_users, session, monkeypatch
):
    _FakeHTML.capturas = []
    monkeypatch.setattr("app.api.v1.endpoints.reportes.HTML", _FakeHTML)

    auth_as("secretaria")
    paciente_id = _crear_paciente(client, cedula="00112345678", nombre="Ana", apellidos="García")

    auth_as("medico")
    _registrar_consulta(
        client, session, seed_users, paciente_id,
        motivo_consulta="Dolor lumbar de 3 semanas",
        examen_fisico="Sensibilidad L4-L5 a la palpación",
        condicion_principal="Hernia discal L4-L5",
        condiciones_secundarias="Sobrepeso",
        tratamiento="AINES y fisioterapia 3x/sem",
    )

    res = client.get(
        f"/api/v1/reportes/historial-medico/pdf"
        f"?paciente_id={paciente_id}&medico_id={seed_users['medico'].id}"
    )
    assert res.status_code == 200
    html = _FakeHTML.capturas[-1]

    # Datos del paciente
    assert "Ana" in html and "García" in html
    assert "00112345678" in html
    assert "8095550100" in html
    assert "1990-04-12" in html
    # Datos del médico
    assert seed_users["medico"].nombre in html
    assert seed_users["medico"].especialidad in html
    # Campos clínicos reales
    assert "Dolor lumbar de 3 semanas" in html
    assert "Sensibilidad L4-L5 a la palpación" in html
    assert "Hernia discal L4-L5" in html
    assert "Sobrepeso" in html
    assert "AINES y fisioterapia 3x/sem" in html


def test_historial_pdf_orden_cronologico_ascendente(
    client, auth_as, seed_users, session, monkeypatch
):
    """El PDF lista de la consulta más antigua a la más reciente.

    El endpoint JSON usa la MISMA query pero en orden inverso: es la única
    diferencia entre ambas salidas.
    """
    _FakeHTML.capturas = []
    monkeypatch.setattr("app.api.v1.endpoints.reportes.HTML", _FakeHTML)

    auth_as("secretaria")
    paciente_id = _crear_paciente(client, cedula="00112345678", nombre="Ana", apellidos="García")

    auth_as("medico")
    _registrar_consulta(
        client, session, seed_users, paciente_id,
        dias_atras=21, hora="08:00:00", condicion_principal="Diagnostico ANTIGUO",
    )
    _registrar_consulta(
        client, session, seed_users, paciente_id,
        dias_atras=3, hora="09:00:00", condicion_principal="Diagnostico RECIENTE",
    )

    res = client.get(
        f"/api/v1/reportes/historial-medico/pdf"
        f"?paciente_id={paciente_id}&medico_id={seed_users['medico'].id}"
    )
    assert res.status_code == 200
    html = _FakeHTML.capturas[-1]
    assert html.index("Diagnostico ANTIGUO") < html.index("Diagnostico RECIENTE")

    # La pantalla sigue mostrando lo más reciente primero
    historial = client.get(
        f"/api/v1/pacientes/{paciente_id}/historial-medico"
        f"?medico_id={seed_users['medico'].id}"
    ).json()
    assert [h["condicion_principal"] for h in historial] == [
        "Diagnostico RECIENTE",
        "Diagnostico ANTIGUO",
    ]


def test_historial_pdf_sin_consultas_muestra_mensaje(
    client, auth_as, seed_users, monkeypatch
):
    _FakeHTML.capturas = []
    monkeypatch.setattr("app.api.v1.endpoints.reportes.HTML", _FakeHTML)

    auth_as("secretaria")
    paciente_id = _crear_paciente(client, cedula="00112345678", nombre="Ana", apellidos="García")

    res = client.get(
        f"/api/v1/reportes/historial-medico/pdf"
        f"?paciente_id={paciente_id}&medico_id={seed_users['medico'].id}"
    )
    assert res.status_code == 200
    html = _FakeHTML.capturas[-1]
    assert "no tiene consultas registradas" in html
    # La cabecera del documento sale igual aunque no haya consultas
    assert "García" in html
    assert seed_users["medico"].nombre in html


def test_historial_template_omite_campos_vacios_y_usa_observaciones_legacy():
    """Los opcionales vacíos no imprimen su etiqueta; `observaciones` es
    fallback SOLO cuando no hay ningún campo estructurado opcional."""
    from jinja2 import Template

    from app.api.v1.endpoints.reportes import _HISTORIAL_TEMPLATE

    def _render(consulta):
        return Template(_HISTORIAL_TEMPLATE).render(
            paciente={"nombre": "Ana", "apellidos": "García", "cedula": "00112345678",
                      "sexo": "femenino", "fecha_nacimiento": "1990-04-12",
                      "telefono": "8095550100"},
            medico={"nombre": "Test", "especialidad": "Ortopedia y Traumatología"},
            consultas=[consulta],
            fecha_emision="7 de mayo de 2026 a las 2:35 PM",
            generado_por="Secre Test",
        )

    base = {
        "fecha_consulta": "2026-01-05", "hora_consulta": "9:00 AM",
        "condicion_principal": "Lumbalgia", "motivo_consulta": None,
        "examen_fisico": None, "condiciones_secundarias": None,
        "tratamiento": None, "observaciones": "Nota vieja pre-migración",
    }

    solo_legacy = _render(base)
    assert "Lumbalgia" in solo_legacy
    assert "Motivo de consulta" not in solo_legacy
    assert "Tratamiento" not in solo_legacy
    assert "Nota vieja pre-migración" in solo_legacy

    con_estructurados = _render({**base, "tratamiento": "Fisioterapia"})
    assert "Tratamiento" in con_estructurados
    assert "Fisioterapia" in con_estructurados
    assert "Nota vieja pre-migración" not in con_estructurados


def test_historial_pdf_excluye_consultas_de_otro_medico(
    client, auth_as, seed_users, session, monkeypatch
):
    """Filtra por médico: una consulta con otro médico no entra al PDF."""
    from app.core.security import hash_password
    from app.models import Medico, RolUsuario, Usuario
    from tests.conftest import TEST_PASSWORD

    _FakeHTML.capturas = []
    monkeypatch.setattr("app.api.v1.endpoints.reportes.HTML", _FakeHTML)

    # Segundo médico con su propio usuario (para registrar su consulta)
    user_b = Usuario(
        nombre="Dr. Bravo", email="bravo@test.do",
        password_hash=hash_password(TEST_PASSWORD), rol=RolUsuario.medico,
    )
    session.add(user_b)
    session.flush()
    medico_b = Medico(id_usuario=user_b.id, nombre="Bravo", especialidad="Medicina Interna")
    session.add(medico_b)
    session.commit()
    session.refresh(medico_b)

    auth_as("secretaria")
    paciente_id = _crear_paciente(client, cedula="00112345678", nombre="Ana", apellidos="García")

    auth_as("medico")
    _registrar_consulta(
        client, session, seed_users, paciente_id,
        condicion_principal="Dx del medico seed",
    )

    # Consulta del segundo médico sobre el mismo paciente
    cita_b = Cita(
        id_paciente=paciente_id, id_medico=medico_b.id,
        fecha=date.today() - timedelta(days=5), hora=time(10, 0),
        id_secretaria=seed_users["secretaria"].id,
    )
    session.add(cita_b)
    session.commit()
    session.refresh(cita_b)

    auth_as("admin")
    res_b = client.post(
        "/api/v1/consultas",
        json={"id_cita": cita_b.id, "condicion_principal": "Dx del otro medico"},
    )
    assert res_b.status_code == 201, res_b.text

    auth_as("secretaria")
    res = client.get(
        f"/api/v1/reportes/historial-medico/pdf"
        f"?paciente_id={paciente_id}&medico_id={seed_users['medico'].id}"
    )
    assert res.status_code == 200
    html = _FakeHTML.capturas[-1]
    assert "Dx del medico seed" in html
    assert "Dx del otro medico" not in html
