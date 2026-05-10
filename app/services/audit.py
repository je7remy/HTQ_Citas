"""Servicio de auditoría — registra todas las acciones críticas."""
from typing import Optional

from sqlmodel import Session

from app.core.datetime_utils import ahora_local
from app.models import AccionAuditoria, Auditoria, Usuario


def registrar_auditoria(
    session: Session,
    *,
    usuario: Optional[Usuario],
    accion: AccionAuditoria,
    tabla: str,
    id_registro: Optional[int] = None,
    detalle: Optional[str] = None,
    ip_origen: Optional[str] = None,
) -> None:
    """Inserta un registro en la tabla auditoria. No hace commit explícito;
    se confía en el commit de la operación principal para mantener atomicidad.

    El nombre del usuario se denormaliza en `nombre_usuario` para que la consulta
    sea directa (sin JOIN) y para preservar la trazabilidad incluso si el
    usuario se elimina o renombra después.
    """
    log = Auditoria(
        id_usuario=usuario.id if usuario else None,
        nombre_usuario=usuario.nombre if usuario else "[sistema]",
        accion=accion,
        tabla_afectada=tabla,
        id_registro=id_registro,
        detalle=detalle,
        ip_origen=ip_origen,
        fecha_hora=ahora_local(),
    )
    session.add(log)
