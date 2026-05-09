"""Manejo unificado de fechas y horas para el SGCM.

Toda la aplicación opera en zona horaria America/Santo_Domingo (UTC-4, sin
horario de verano). Este módulo centraliza la única fuente de "ahora" y los
helpers de formato, de modo que reportes, auditoría y validaciones temporales
coincidan con el reloj real del hospital.
"""
from datetime import datetime, time
from zoneinfo import ZoneInfo

TZ_DOMINICANA = ZoneInfo("America/Santo_Domingo")
TZ_UTC = ZoneInfo("UTC")

_MESES_ES = {
    1: "enero", 2: "febrero", 3: "marzo", 4: "abril",
    5: "mayo", 6: "junio", 7: "julio", 8: "agosto",
    9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre",
}


def ahora_local() -> datetime:
    """Datetime actual aware en zona horaria de República Dominicana."""
    return datetime.now(TZ_DOMINICANA)


def _a_local(dt: datetime) -> datetime:
    # Datos históricos guardados antes de la migración a TIMESTAMPTZ son naive
    # y representan UTC; los normalizamos antes de convertir.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ_UTC)
    return dt.astimezone(TZ_DOMINICANA)


def formatear_fecha_hora(dt: datetime) -> str:
    """Formatea un datetime para UI/reportes: 'dd/mm/aaaa HH:MM:SS' en hora RD."""
    return _a_local(dt).strftime("%d/%m/%Y %H:%M:%S")


def formatear_fecha_emision(dt: datetime | None = None) -> str:
    """'8 de mayo de 2026 a las 15:35' en hora RD. Sin argumento usa ahora."""
    local = _a_local(dt) if dt is not None else ahora_local()
    return (
        f"{local.day} de {_MESES_ES[local.month]} de {local.year} "
        f"a las {local.strftime('%H:%M')}"
    )


def formatear_hora_12(hora: time | None) -> str:
    """Convierte un objeto time (24h) a '2:30 PM' (12h con AM/PM).

    Solo presentacional — la BD y el backend siguen operando en 24h.
    Devuelve '' si recibe None.
    """
    if hora is None:
        return ""
    h = hora.hour
    m = str(hora.minute).zfill(2)
    ampm = "PM" if h >= 12 else "AM"
    h12 = 12 if h % 12 == 0 else h % 12
    return f"{h12}:{m} {ampm}"
