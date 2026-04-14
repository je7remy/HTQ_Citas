"""Servicio de auditoría — registra todas las acciones críticas."""
from typing import Optional

from sqlmodel import Session

from app.models import AccionAuditoria, Auditoria


def registrar_auditoria(
    session: Session,
    *,
    id_usuario: Optional[int],
    accion: AccionAuditoria,
    tabla: str,
    id_registro: Optional[int] = None,
    detalle: Optional[str] = None,
    ip_origen: Optional[str] = None,
) -> None:
    """Inserta un registro en la tabla auditoria. No hace commit explícito;
    se confía en el commit de la operación principal para mantener atomicidad."""
    log = Auditoria(
        id_usuario=id_usuario,
        accion=accion,
        tabla_afectada=tabla,
        id_registro=id_registro,
        detalle=detalle,
        ip_origen=ip_origen,
    )
    session.add(log)
