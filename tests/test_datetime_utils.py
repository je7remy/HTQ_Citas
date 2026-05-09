"""Tests del módulo central de fechas/horas (zona horaria RD)."""
from datetime import datetime, timezone

from app.core.datetime_utils import (
    TZ_DOMINICANA,
    ahora_local,
    formatear_fecha_emision,
    formatear_fecha_hora,
)


def test_ahora_local_retorna_aware_en_zona_rd():
    dt = ahora_local()
    assert dt.tzinfo is not None, "ahora_local() debe retornar un datetime aware"
    # RD es UTC-4 sin horario de verano
    assert dt.utcoffset().total_seconds() == -4 * 3600


def test_ahora_local_y_utc_representan_mismo_instante():
    local = ahora_local()
    utc = datetime.now(timezone.utc)
    delta = abs((local - utc).total_seconds())
    assert delta < 2


def test_formatear_fecha_hora_convierte_utc_aware_a_rd():
    # 19:35 UTC = 15:35 hora RD
    dt_utc = datetime(2026, 5, 8, 19, 35, 0, tzinfo=timezone.utc)
    assert formatear_fecha_hora(dt_utc) == "08/05/2026 15:35:00"


def test_formatear_fecha_hora_naive_se_asume_utc():
    """Compatibilidad con datos legacy (TIMESTAMP naive en UTC)."""
    dt_naive = datetime(2026, 5, 8, 19, 35, 0)
    assert formatear_fecha_hora(dt_naive) == "08/05/2026 15:35:00"


def test_formatear_fecha_hora_aware_local_no_aplica_shift():
    dt_local = datetime(2026, 5, 8, 15, 35, 0, tzinfo=TZ_DOMINICANA)
    assert formatear_fecha_hora(dt_local) == "08/05/2026 15:35:00"


def test_formatear_fecha_emision_formato_largo_en_espanol():
    dt = datetime(2026, 5, 8, 15, 35, 0, tzinfo=TZ_DOMINICANA)
    assert formatear_fecha_emision(dt) == "8 de mayo de 2026 a las 15:35"


def test_formatear_fecha_emision_convierte_utc_a_rd():
    """Mismo instante, distinto tz: el texto refleja la hora RD."""
    dt_utc = datetime(2026, 5, 8, 19, 35, 0, tzinfo=timezone.utc)
    assert formatear_fecha_emision(dt_utc) == "8 de mayo de 2026 a las 15:35"


def test_formatear_fecha_emision_sin_arg_usa_ahora_local():
    txt = formatear_fecha_emision()
    assert " de " in txt
    assert " a las " in txt
    # El año actual debe aparecer (validación laxa pero útil)
    assert str(ahora_local().year) in txt
