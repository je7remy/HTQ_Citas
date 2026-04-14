"""CU-15 — Consulta de auditoría por el administrador.

Permite filtrar por usuario, acción, tabla afectada y rango de fechas,
con paginación y orden descendente por fecha.
"""
from datetime import date as date_type
from datetime import datetime, time

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlmodel import Session, select

from app.api.deps import require_roles
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
    if desde:
        base = base.where(Auditoria.fecha_hora >= datetime.combine(desde, time.min))
    if hasta:
        base = base.where(Auditoria.fecha_hora <= datetime.combine(hasta, time.max))

    total = session.exec(select(func.count()).select_from(base.subquery())).one()

    items = session.exec(
        base.order_by(Auditoria.fecha_hora.desc()).offset(offset).limit(limit)
    ).all()

    return AuditoriaPage(total=total, limit=limit, offset=offset, items=items)
