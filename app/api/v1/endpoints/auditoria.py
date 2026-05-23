"""CU-15 — Consulta de auditoría por el administrador.

Permite filtrar por usuario, acción, tabla afectada y rango de fechas,
con paginación y orden descendente por fecha.

CONTEXTO: solo de lectura. La tabla `auditoria` se escribe desde
app/services/audit.py invocado por los demás endpoints — este endpoint
solo expone los datos al admin via la pantalla de auditoría.

Endpoint único (GET /auditoria) que devuelve AuditoriaPage paginada.
El frontend usa `limit/offset` clásicos (no cursor) porque la cantidad
de registros queda manejable para el HTQPJB (decenas de miles, no
millones) y permite saltar a página directa.

OJO: el filtro `tabla` es match EXACTO (no like). La pantalla muestra
un dropdown con los nombres de tabla válidos para no obligar al admin
a recordar la convención (singular en plural minúscula: 'usuarios',
'pacientes', 'citas', 'consultas', 'medicos', 'horarios',
'especialidades', 'respaldos', 'reportes').
"""
from datetime import date as date_type
from datetime import datetime, time

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlmodel import Session, select

from app.api.deps import require_roles
from app.core.datetime_utils import TZ_DOMINICANA
from app.db.session import get_session
from app.models import AccionAuditoria, Auditoria, RolUsuario, Usuario
from app.schemas import AuditoriaPage, AuditoriaRead

router = APIRouter(prefix="/auditoria", tags=["auditoria"])

_admin = require_roles(RolUsuario.admin)


@router.get("", response_model=AuditoriaPage)
def consultar_auditoria(
    id_usuario: int | None = None,
    accion: AccionAuditoria | None = None,
    tabla: str | None = Query(default=None, description="Nombre exacto de tabla afectada"),
    desde: date_type | None = None,
    hasta: date_type | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
    _: Usuario = Depends(_admin),
):
    base = select(Auditoria)
    if id_usuario is not None:
        base = base.where(Auditoria.id_usuario == id_usuario)
    if accion is not None:
        base = base.where(Auditoria.accion == accion)
    if tabla:
        base = base.where(Auditoria.tabla_afectada == tabla)
    # `time.min` y `time.max`: el filtro recibe solo `date`, pero la
    # columna es TIMESTAMPTZ. Construimos el bound completo en TZ
    # dominicana para que "desde 2026-05-15" empiece a las 00:00:00 RD
    # y "hasta 2026-05-15" termine a las 23:59:59.999999 RD. Sin esto,
    # filtrar por un solo día devolvería filas vacías (la fecha sería
    # comparada contra el inicio del día y todo lo de ese mismo día
    # caería FUERA del límite superior).
    if desde:
        base = base.where(
            Auditoria.fecha_hora >= datetime.combine(desde, time.min, tzinfo=TZ_DOMINICANA)
        )
    if hasta:
        base = base.where(
            Auditoria.fecha_hora <= datetime.combine(hasta, time.max, tzinfo=TZ_DOMINICANA)
        )

    # `count(*) from (subquery)`: contamos el total ANTES de aplicar
    # offset/limit para que el frontend sepa cuántas páginas hay.
    # Es un round-trip extra pero el patrón estándar de paginación.
    total = session.exec(select(func.count()).select_from(base.subquery())).one()

    items = session.exec(
        base.order_by(Auditoria.fecha_hora.desc()).offset(offset).limit(limit)
    ).all()

    return AuditoriaPage(total=total, limit=limit, offset=offset, items=items)
