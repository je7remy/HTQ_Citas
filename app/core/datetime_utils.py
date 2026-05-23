"""Manejo unificado de fechas y horas para el SGCM.

Toda la aplicación opera en zona horaria America/Santo_Domingo (UTC-4, sin
horario de verano). Este módulo centraliza la única fuente de "ahora" y los
helpers de formato, de modo que reportes, auditoría y validaciones temporales
coincidan con el reloj real del hospital.

CONTEXTO: República Dominicana NO observa DST (Decreto No. 38-04 que
restableció el horario estándar). Por eso podemos pinear UTC-4 con
seguridad sin temer saltos primaverales. Si esto cambia legalmente,
ZoneInfo("America/Santo_Domingo") lo maneja automáticamente.

IMPORTANTE: nunca usar `datetime.now()` ni `datetime.utcnow()` directos
en el resto del proyecto. Esos devuelven naive datetimes en la hora del
contenedor (UTC), y PostgreSQL los interpreta como UTC al guardar en
TIMESTAMPTZ — entonces los datos se desfasan 4 horas. Usar SIEMPRE
ahora_local() para timestamps que vayan a BD o UI.
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
    """Datetime actual aware en zona horaria de República Dominicana.

    Esta es la ÚNICA fuente de tiempo del SGCM. Si necesitas saber qué
    hora es para registro de auditoría, validación de cita futura/pasada,
    fecha_creacion en un modelo, etc., llama aquí.
    """
    return datetime.now(TZ_DOMINICANA)


def _a_local(dt: datetime) -> datetime:
    # Normaliza un datetime cualquiera a TZ dominicana.
    # Datos históricos guardados antes de la migración a TIMESTAMPTZ son naive
    # y representan UTC; los normalizamos antes de convertir.
    # OJO: tratar un naive como UTC es una asunción razonable para datos
    # legacy del SGCM, pero NO es universal — si llegaran datos naive de
    # otra fuente (CSV con horas locales) esta función los desplazaría
    # 4 horas equivocadamente. Hoy ese caso no existe.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ_UTC)
    return dt.astimezone(TZ_DOMINICANA)


def _to_12h(h: int, m: int, s: int | None = None) -> str:
    # Conversión 24h → 12h con AM/PM. Casos típicos:
    #   13:30 → "1:30 PM"
    #   00:15 → "12:15 AM"
    #   12:00 → "12:00 PM"
    # El truco `12 if h % 12 == 0 else h % 12` es para que las 0:00 y las
    # 12:00 aparezcan como "12:00 AM" y "12:00 PM" respectivamente (en
    # vez de "0:00 AM" o "0:00 PM").
    ampm = "PM" if h >= 12 else "AM"
    h12 = 12 if h % 12 == 0 else h % 12
    if s is None:
        return f"{h12}:{str(m).zfill(2)} {ampm}"
    return f"{h12}:{str(m).zfill(2)}:{str(s).zfill(2)} {ampm}"


def formatear_fecha_hora(dt: datetime) -> str:
    """Formatea un datetime para UI/reportes: 'dd/mm/aaaa h:MM:SS AM/PM' en hora RD.

    Usado en la pantalla de auditoría y en los PDFs detallados.
    Ejemplo: '15/05/2026 9:35:21 AM'.
    """
    local = _a_local(dt)
    return f"{local.strftime('%d/%m/%Y')} {_to_12h(local.hour, local.minute, local.second)}"


def formatear_fecha_emision(dt: datetime | None = None) -> str:
    """'8 de mayo de 2026 a las 3:35 PM' en hora RD. Sin argumento usa ahora.

    Para el pie de los PDFs administrativos: línea de "documento emitido el…".
    El formato largo es a propósito — los reportes oficiales del HTQPJB
    se imprimen y firman, y los meses se quieren ver escritos.
    """
    local = _a_local(dt) if dt is not None else ahora_local()
    return (
        f"{local.day} de {_MESES_ES[local.month]} de {local.year} "
        f"a las {_to_12h(local.hour, local.minute)}"
    )


def formatear_hora_12(hora: time | None) -> str:
    """Convierte un objeto time (24h) a '2:30 PM' (12h con AM/PM).

    Solo presentacional — la BD y el backend siguen operando en 24h.
    Devuelve '' si recibe None.

    Lo usa la Agenda del Día para llenar el campo `hora_12h` que el
    frontend muestra al lado de cada cita.
    """
    if hora is None:
        return ""
    return _to_12h(hora.hour, hora.minute)
