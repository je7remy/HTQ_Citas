"""CU-16 — Gestión de respaldos del SGCM (solo administrador).

Endpoints:
  POST   /respaldos              — crea un respaldo (local | externo | nube)
  GET    /respaldos              — lista respaldos con filtros opcionales
  GET    /respaldos/{id}         — detalle de un respaldo
  DELETE /respaldos/{id}         — elimina el registro (no el archivo físico)
  GET    /respaldos/{id}/descargar — descarga el .sql si es respaldo local
"""
from datetime import date as date_type
from datetime import datetime, time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from sqlmodel import Session, select

from app.api.deps import require_roles
from app.core.datetime_utils import TZ_DOMINICANA
from app.db.session import get_session
from app.models import (
    AccionAuditoria,
    EstadoRespaldo,
    Respaldo,
    RolUsuario,
    TipoRespaldo,
    Usuario,
)
from app.schemas import RespaldoCreate, RespaldoRead
from app.services.audit import registrar_auditoria
from app.services.backup import crear_respaldo

router = APIRouter(prefix="/respaldos", tags=["respaldos"])

_admin = require_roles(RolUsuario.admin)


@router.post("", response_model=RespaldoRead, status_code=status.HTTP_201_CREATED)
def crear(
    payload: RespaldoCreate,
    request: Request,
    session: Session = Depends(get_session),
    actor: Usuario = Depends(_admin),
):
    if payload.tipo == "nube" and not payload.proveedor_nube:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Para respaldo de tipo 'nube' debe especificar 'proveedor_nube'.",
        )

    respaldo = crear_respaldo(
        session,
        usuario=actor,
        tipo=payload.tipo,
        proveedor_nube=payload.proveedor_nube,
    )

    registrar_auditoria(
        session,
        usuario=actor,
        accion=AccionAuditoria.CREATE,
        tabla="respaldos",
        id_registro=respaldo.id,
        detalle=(
            f"Respaldo {respaldo.tipo}"
            + (f"/{respaldo.proveedor_nube}" if respaldo.proveedor_nube else "")
            + f" → estado={respaldo.estado}"
        ),
        ip_origen=request.client.host if request.client else None,
    )
    session.commit()
    session.refresh(respaldo)

    return respaldo


@router.get("", response_model=list[RespaldoRead])
def listar(
    tipo: Optional[TipoRespaldo] = None,
    estado: Optional[EstadoRespaldo] = None,
    desde: Optional[date_type] = None,
    hasta: Optional[date_type] = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
    _: Usuario = Depends(_admin),
):
    stmt = select(Respaldo)
    if tipo is not None:
        stmt = stmt.where(Respaldo.tipo == tipo.value)
    if estado is not None:
        stmt = stmt.where(Respaldo.estado == estado.value)
    if desde is not None:
        stmt = stmt.where(
            Respaldo.fecha_inicio >= datetime.combine(desde, time.min, tzinfo=TZ_DOMINICANA)
        )
    if hasta is not None:
        stmt = stmt.where(
            Respaldo.fecha_inicio <= datetime.combine(hasta, time.max, tzinfo=TZ_DOMINICANA)
        )
    stmt = stmt.order_by(Respaldo.fecha_inicio.desc()).offset(offset).limit(limit)
    return session.exec(stmt).all()


@router.get("/{respaldo_id}", response_model=RespaldoRead)
def obtener(
    respaldo_id: int,
    session: Session = Depends(get_session),
    _: Usuario = Depends(_admin),
):
    r = session.get(Respaldo, respaldo_id)
    if not r:
        raise HTTPException(404, "Respaldo no encontrado.")
    return r


@router.delete("/{respaldo_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar(
    respaldo_id: int,
    request: Request,
    session: Session = Depends(get_session),
    actor: Usuario = Depends(_admin),
):
    # IMPORTANTE: borra el REGISTRO, NO el archivo físico. El .sql en
    # disco/USB/nube se preserva — el admin debe limpiarlo a mano si
    # quiere liberar espacio. Esto es deliberado para no perder un
    # respaldo crítico por accidente. El detalle de auditoría incluye
    # la ruta destino para que el admin sepa dónde está el archivo
    # que ya no aparece en la pantalla.
    r = session.get(Respaldo, respaldo_id)
    if not r:
        raise HTTPException(404, "Respaldo no encontrado.")

    detalle = (
        f"Eliminación de registro de respaldo (archivo físico se conserva en "
        f"{r.ruta_destino})"
    )
    session.delete(r)
    registrar_auditoria(
        session,
        usuario=actor,
        accion=AccionAuditoria.DELETE,
        tabla="respaldos",
        id_registro=respaldo_id,
        detalle=detalle,
        ip_origen=request.client.host if request.client else None,
    )
    session.commit()
    return None


@router.get("/{respaldo_id}/descargar")
def descargar(
    respaldo_id: int,
    session: Session = Depends(get_session),
    _: Usuario = Depends(_admin),
):
    # Solo respaldos LOCAL se pueden descargar por HTTP — los externos
    # están en un USB/montaje que el contenedor no puede stremear sin
    # complicar montajes; los de nube se descargan desde la consola del
    # proveedor (S3/GCS/Azure). El mensaje de error incluye la ruta
    # exacta para que el admin sepa a dónde ir.
    r = session.get(Respaldo, respaldo_id)
    if not r:
        raise HTTPException(404, "Respaldo no encontrado.")

    if r.tipo != TipoRespaldo.local.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Solo se pueden descargar respaldos de tipo 'local'. "
                f"Este respaldo es '{r.tipo}' y se encuentra en: {r.ruta_destino}"
            ),
        )

    if r.estado != EstadoRespaldo.completado.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"El respaldo no está completado (estado actual: {r.estado}).",
        )

    # 410 GONE (no 404) cuando el archivo desapareció: hace explícito al
    # admin que el registro existe pero el archivo se perdió/limpió.
    # 404 sugeriría que la ruta nunca existió.
    ruta = Path(r.ruta_destino)
    if not ruta.exists():
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=f"El archivo ya no existe en el servidor: {r.ruta_destino}",
        )

    return FileResponse(
        path=str(ruta),
        media_type="application/sql",
        filename=ruta.name,
    )
