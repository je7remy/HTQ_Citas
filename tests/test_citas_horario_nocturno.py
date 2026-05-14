"""Bug "horario nocturno": validación de fecha/hora pasada en POST /citas.

Reproducción del bug original:
- A las 11:00 PM la secretaria a veces no podía crear citas para el día
  siguiente; otras veces el sistema sí dejaba registrar citas con una
  hora ya pasada de hoy.
- Causa raíz: faltaba una validación explícita que comparara la fecha+hora
  COMPLETA de la cita contra ahora_local(). Una comparación ingenua de
  solo la hora del día rechaza incorrectamente citas con hora < hora actual
  aunque la fecha sea mañana; la ausencia de validación deja entrar citas
  cuyo instante ya pasó.

Estos tests mockean ahora_local() para forzar el reloj cerca de las 23:00
y de las 00:00 sin depender del wall clock del runner.
"""
from datetime import date, datetime, time, timedelta

from app.core.datetime_utils import TZ_DOMINICANA
import app.services.citas_service as citas_service
import app.services.disponibilidad_service as disponibilidad_service


def _proximo_dia_semana(target_iso: int) -> date:
    """Próxima fecha real (offset >= 1) cuyo isoweekday == target_iso."""
    hoy = date.today()
    for offset in range(1, 15):
        d = hoy + timedelta(days=offset)
        if d.isoweekday() == target_iso:
            return d
    raise RuntimeError("unreachable")


def _crear_paciente(client, cedula: str = "00112345678") -> int:
    res = client.post(
        "/api/v1/pacientes",
        json={
            "cedula": cedula,
            "nombre": "Ana",
            "apellidos": "García",
            "sexo": "femenino",
            "fecha_nacimiento": "1990-04-12",
            "telefono": "8095550100",
        },
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


def _mock_ahora(monkeypatch, dt: datetime) -> None:
    """Inyecta un ahora_local() falso en TODOS los módulos que lo consultan."""
    monkeypatch.setattr(citas_service, "ahora_local", lambda: dt)
    monkeypatch.setattr(disponibilidad_service, "ahora_local", lambda: dt)


def test_crear_cita_a_las_23_para_hoy_mismo_se_rechaza(
    client, auth_as, seed_users, monkeypatch
):
    """A las 11 PM, una cita para HOY a las 09:00 (que ya pasó) debe rechazarse."""
    auth_as("secretaria")
    paciente_id = _crear_paciente(client)
    medico_id = seed_users["medico"].id

    hoy = _proximo_dia_semana(1)  # un lunes real lo simulamos como "hoy"
    fake_now = datetime.combine(hoy, time(23, 0), tzinfo=TZ_DOMINICANA)
    _mock_ahora(monkeypatch, fake_now)

    res = client.post(
        "/api/v1/citas",
        json={
            "id_paciente": paciente_id,
            "id_medico": medico_id,
            "fecha": hoy.isoformat(),
            "hora": "09:00:00",
        },
    )
    assert res.status_code == 409, res.text
    assert "pasad" in res.json()["detail"].lower()


def test_crear_cita_a_las_23_para_manana_se_permite(
    client, auth_as, seed_users, monkeypatch
):
    """A las 11 PM, una cita para MAÑANA a las 09:00 debe permitirse.

    Es el caso que el bug bloqueaba: una validación que compare solo la
    hora del día rechazaría 09:00 mañana porque 09:00 < 23:00.
    """
    auth_as("secretaria")
    paciente_id = _crear_paciente(client)
    medico_id = seed_users["medico"].id

    hoy = _proximo_dia_semana(1)        # lunes
    manana = hoy + timedelta(days=1)    # martes (L-V tiene horario)
    fake_now = datetime.combine(hoy, time(23, 0), tzinfo=TZ_DOMINICANA)
    _mock_ahora(monkeypatch, fake_now)

    res = client.post(
        "/api/v1/citas",
        json={
            "id_paciente": paciente_id,
            "id_medico": medico_id,
            "fecha": manana.isoformat(),
            "hora": "09:00:00",
        },
    )
    assert res.status_code == 201, res.text


def test_crear_cita_a_las_23_para_pasado_manana_se_permite(
    client, auth_as, seed_users, monkeypatch
):
    """A las 11 PM, una cita para PASADO MAÑANA debe permitirse sin reservas."""
    auth_as("secretaria")
    paciente_id = _crear_paciente(client)
    medico_id = seed_users["medico"].id

    hoy = _proximo_dia_semana(1)           # lunes
    pasado_manana = hoy + timedelta(days=2)  # miércoles
    fake_now = datetime.combine(hoy, time(23, 0), tzinfo=TZ_DOMINICANA)
    _mock_ahora(monkeypatch, fake_now)

    res = client.post(
        "/api/v1/citas",
        json={
            "id_paciente": paciente_id,
            "id_medico": medico_id,
            "fecha": pasado_manana.isoformat(),
            "hora": "08:30:00",
        },
    )
    assert res.status_code == 201, res.text


def test_crear_cita_a_las_00_00_recien_pasado_medianoche(
    client, auth_as, seed_users, monkeypatch
):
    """Recién pasada la medianoche (00:05), una cita para HOY a las 09:00 debe permitirse.

    Caso extremo: la 'fecha actual' acaba de cambiar entre el cálculo de
    disponibilidad y la inserción. La validación correcta compara fecha+hora
    completa contra ahora_local() y acepta hoy 09:00 (todavía faltan ~9h).
    """
    auth_as("secretaria")
    paciente_id = _crear_paciente(client)
    medico_id = seed_users["medico"].id

    hoy = _proximo_dia_semana(1)
    fake_now = datetime.combine(hoy, time(0, 5), tzinfo=TZ_DOMINICANA)
    _mock_ahora(monkeypatch, fake_now)

    res = client.post(
        "/api/v1/citas",
        json={
            "id_paciente": paciente_id,
            "id_medico": medico_id,
            "fecha": hoy.isoformat(),
            "hora": "09:00:00",
        },
    )
    assert res.status_code == 201, res.text


def test_proxima_disponibilidad_no_devuelve_slots_pasados_a_las_23(
    client, auth_as, seed_users, monkeypatch
):
    """A las 23:00 con horario 8-12, la sugerencia NUNCA puede caer hoy."""
    auth_as("secretaria")
    medico_id = seed_users["medico"].id

    hoy = _proximo_dia_semana(1)  # lunes
    fake_now = datetime.combine(hoy, time(23, 0), tzinfo=TZ_DOMINICANA)
    _mock_ahora(monkeypatch, fake_now)

    res = client.get(f"/api/v1/medicos/{medico_id}/proxima-disponibilidad")
    assert res.status_code == 200
    body = res.json()
    assert body is not None
    assert body["fecha"] > hoy.isoformat(), "La sugerencia no debe ser hoy."
    # El primer slot ofrecido al día siguiente debe ser el inicio del horario.
    assert body["hora"] == "08:00:00"


def test_reprogramar_cita_a_fecha_pasada_se_rechaza(
    client, auth_as, seed_users, monkeypatch
):
    """PATCH también debe rechazar una reprogramación a una fecha/hora pasada."""
    auth_as("secretaria")
    paciente_id = _crear_paciente(client)
    medico_id = seed_users["medico"].id

    hoy = _proximo_dia_semana(1)
    manana = hoy + timedelta(days=1)

    # Creamos la cita "de mañana" mientras estamos en hoy 09:00 (futuro válido).
    fake_now_creacion = datetime.combine(hoy, time(9, 0), tzinfo=TZ_DOMINICANA)
    _mock_ahora(monkeypatch, fake_now_creacion)
    creada = client.post(
        "/api/v1/citas",
        json={
            "id_paciente": paciente_id,
            "id_medico": medico_id,
            "fecha": manana.isoformat(),
            "hora": "10:00:00",
        },
    )
    assert creada.status_code == 201, creada.text
    cita_id = creada.json()["id"]

    # Ahora son las 11 PM. Reprogramar a "hoy 09:00" (pasado) debe fallar.
    fake_now_patch = datetime.combine(hoy, time(23, 0), tzinfo=TZ_DOMINICANA)
    _mock_ahora(monkeypatch, fake_now_patch)
    patch = client.patch(
        f"/api/v1/citas/{cita_id}",
        json={"fecha": hoy.isoformat(), "hora": "09:00:00"},
    )
    assert patch.status_code == 409, patch.text
    assert "pasad" in patch.json()["detail"].lower()
