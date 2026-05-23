"""Servicio: calcula la próxima fecha/hora disponible para un médico.

CONTEXTO: alimenta el endpoint /medicos/{id}/proxima-disponibilidad que
el frontend de agenda usa para sugerir "Próximo slot libre del Dr. X".
Esto evita que la secretaria tenga que probar fechas a ciegas.

Configuración:
- Horizonte de búsqueda: 30 días (constante _HORIZONTE_DIAS). Más allá
  consume tiempo y el HTQPJB rara vez agenda con tanto adelanto.
- Granularidad: slots cada 30 minutos. Coincide con cómo se generan
  las citas en el seed y con la práctica de consulta del hospital.
"""
from datetime import date, datetime, time, timedelta

from sqlmodel import Session, select

from app.core.datetime_utils import ahora_local, formatear_hora_12
from app.models import Cita, EstadoCita, Horario, Medico

_HORIZONTE_DIAS = 30
_GRANULARIDAD_MIN = 30

_DIAS_ES = {
    1: "Lunes", 2: "Martes", 3: "Miércoles", 4: "Jueves",
    5: "Viernes", 6: "Sábado", 7: "Domingo",
}
_MESES_ES = {
    1: "enero", 2: "febrero", 3: "marzo", 4: "abril",
    5: "mayo", 6: "junio", 7: "julio", 8: "agosto",
    9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre",
}


def _slots_de_horario(h: Horario) -> list[time]:
    """Genera los slots de 30 min entre hora_inicio (inclusive) y hora_fin (exclusivo)."""
    inicio = datetime.combine(date.today(), h.hora_inicio)
    fin = datetime.combine(date.today(), h.hora_fin)
    slots: list[time] = []
    cur = inicio
    while cur < fin:
        slots.append(cur.time())
        cur += timedelta(minutes=_GRANULARIDAD_MIN)
    return slots


def proxima_disponibilidad(session: Session, id_medico: int) -> dict | None:
    """Retorna el primer slot disponible del médico en los próximos 30 días, o None.

    Disponible = slot dentro de un horario activo + sin cita activa registrada.

    Estrategia (O(días × slots × citas_del_día)):
      1. Trae todos los horarios activos del médico, agrupados por día de semana.
      2. Itera día por día desde hoy hasta hoy+30.
      3. Para cada día, genera los slots de 30 min de cada bloque, filtra
         los que ya pasaron si es hoy, descarta los ocupados, devuelve
         el primero libre.

    Devuelve None si:
      - El médico no existe o está inactivo.
      - No tiene horarios activos.
      - No hay slots libres en el horizonte (caso extremo de agenda llena).

    El dict incluye versiones legibles en español ("Lunes 15 de mayo de
    2026" / "2:30 PM") para que el frontend lo muestre directo, sin
    formateo adicional.
    """
    medico = session.get(Medico, id_medico)
    if not medico or not medico.activo:
        return None

    ahora = ahora_local()
    hoy = ahora.date()
    hora_actual = ahora.time()

    horarios_por_dia: dict[int, list[Horario]] = {}
    for h in session.exec(
        select(Horario).where(
            Horario.id_medico == id_medico,
            Horario.activo == True,  # noqa: E712
        )
    ).all():
        horarios_por_dia.setdefault(h.dia_semana, []).append(h)

    if not horarios_por_dia:
        return None

    for offset in range(_HORIZONTE_DIAS):
        d = hoy + timedelta(days=offset)
        bloques = horarios_por_dia.get(d.isoweekday(), [])
        if not bloques:
            continue

        candidatos: list[time] = []
        for bloque in bloques:
            candidatos.extend(_slots_de_horario(bloque))
        candidatos.sort()

        if d == hoy:
            candidatos = [s for s in candidatos if s > hora_actual]
        if not candidatos:
            continue

        ocupadas = {
            c.hora
            for c in session.exec(
                select(Cita).where(
                    Cita.id_medico == id_medico,
                    Cita.fecha == d,
                    Cita.estado != EstadoCita.cancelada,
                )
            ).all()
        }

        for slot in candidatos:
            if slot not in ocupadas:
                return {
                    "fecha": d.isoformat(),
                    "hora": slot.isoformat(),
                    "fecha_legible": (
                        f"{_DIAS_ES[d.isoweekday()]} "
                        f"{d.day} de {_MESES_ES[d.month]} de {d.year}"
                    ),
                    "hora_legible": formatear_hora_12(slot),
                }

    return None
