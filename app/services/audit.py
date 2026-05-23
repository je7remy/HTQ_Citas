"""Servicio de auditoría — registra todas las acciones críticas.

CONTEXTO: este módulo es la implementación del requerimiento legal
de la Ley 172-13 (Protección de Datos R.D.) que exige bitácora de
operaciones sobre datos personales. CADA endpoint que crea/modifica/
borra una entidad sensible (paciente, cita, consulta, usuario, etc.)
DEBE invocar registrar_auditoria() en la misma transacción.

CUIDADO: si alguien añade un endpoint nuevo y se le olvida auditar,
el sistema queda fuera de cumplimiento legal y no hay forma de saber
quién hizo qué después.
"""
from typing import Optional

from fastapi import Request
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

    IMPORTANTE: no llamar commit aquí. La razón es atomicidad — si el
    INSERT principal (crear paciente, p.ej.) falla y el endpoint hace
    rollback, la fila de auditoría también se va al rollback. Si hiciéramos
    commit acá, quedaríamos con un registro "alguien creó X" sin que
    realmente exista X. La auditoría debe espejar la realidad de la BD.

    `usuario=None` se usa solo para acciones de sistema (seed, jobs
    automáticos). En esos casos se registra como "[sistema]".
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


def registrar_auditoria_reporte(
    session: Session,
    *,
    actor: Usuario,
    request: Request,
    tipo: str,
) -> None:
    """Helper común para los endpoints de reportes: registra la generación y
    hace commit dentro de la misma transacción de lectura.

    OJO: a diferencia de registrar_auditoria(), aquí SÍ se hace commit
    porque los endpoints de reporte son de solo lectura — no tienen
    operación principal con la que sincronizar. Si no comiteamos, el
    insert se descartaría al cerrar la sesión.

    El detalle queda como "Generación de reporte: {tipo}" para que en
    la pantalla de auditoría se vea qué reporte generó cada usuario.
    """
    registrar_auditoria(
        session,
        usuario=actor,
        accion=AccionAuditoria.CREATE,
        tabla="reportes",
        id_registro=None,
        detalle=f"Generación de reporte: {tipo}",
        ip_origen=request.client.host if request.client else None,
    )
    session.commit()
