"""CU-17 — CRUD del catalogo de especialidades del HTQPJB (solo admin para
escrituras; lectura abierta a cualquier rol autenticado).

Endpoints:
  GET    /especialidades            — lista con filtros opcionales
  POST   /especialidades            — crea una especialidad nueva (admin)
  PATCH  /especialidades/{id}       — actualiza nombre/descripcion/activa (admin)
  DELETE /especialidades/{id}       — elimina si no esta en uso (admin)

Decision de diseno: medicos.especialidad sigue siendo VARCHAR sin FK. Para
eliminar una especialidad se verifica que no este referenciada como principal
ni como secundaria en la tabla medicos; si esta en uso devolvemos 409 con
un mensaje explicito sugiriendo desactivarla en lugar de eliminarla.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import or_
from sqlmodel import Session, func, select

from app.api.deps import require_roles
from app.db.session import get_session
from app.models import AccionAuditoria, Especialidad, Medico, RolUsuario, Usuario
from app.schemas import EspecialidadCreate, EspecialidadRead, EspecialidadUpdate
from app.services.audit import registrar_auditoria

router = APIRouter(prefix="/especialidades", tags=["especialidades"])

_admin = require_roles(RolUsuario.admin)
_any = require_roles(RolUsuario.secretaria, RolUsuario.admin, RolUsuario.medico)


def _buscar_por_nombre_ci(session: Session, nombre: str) -> Optional[Especialidad]:
    """Busqueda case-insensitive por nombre, para validar unicidad logica."""
    return session.exec(
        select(Especialidad).where(func.lower(Especialidad.nombre) == nombre.lower())
    ).first()


def _contar_medicos_que_usan(session: Session, nombre: str) -> int:
    """Cuenta medicos que tienen esta especialidad como principal o secundaria.

    Se usa antes de eliminar para prevenir dejar referencias huerfanas en la
    tabla medicos (que no tiene FK al catalogo).
    """
    stmt = select(func.count()).select_from(Medico).where(
        or_(
            Medico.especialidad == nombre,
            Medico.especialidad_secundaria_1 == nombre,
            Medico.especialidad_secundaria_2 == nombre,
        )
    )
    return session.exec(stmt).one()


@router.get("", response_model=list[EspecialidadRead])
def listar(
    activa: Optional[bool] = Query(default=None),
    q: Optional[str] = Query(default=None, description="Filtro parcial por nombre"),
    session: Session = Depends(get_session),
    _: Usuario = Depends(_any),
):
    """Lista el catalogo. Sin filtros devuelve todas (admin necesita ver
    inactivas para reactivarlas). Con `activa=true` devuelve solo las
    disponibles para asignar a un medico."""
    stmt = select(Especialidad)
    if activa is not None:
        stmt = stmt.where(Especialidad.activa == activa)
    if q:
        q_clean = q.strip()
        if q_clean:
            stmt = stmt.where(Especialidad.nombre.ilike(f"%{q_clean}%"))
    stmt = stmt.order_by(Especialidad.nombre)
    return session.exec(stmt).all()


@router.post("", response_model=EspecialidadRead, status_code=status.HTTP_201_CREATED)
def crear(
    payload: EspecialidadCreate,
    request: Request,
    session: Session = Depends(get_session),
    actor: Usuario = Depends(_admin),
):
    nombre = payload.nombre.strip()
    if _buscar_por_nombre_ci(session, nombre) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya existe una especialidad con ese nombre.",
        )
    esp = Especialidad(
        nombre=nombre,
        descripcion=payload.descripcion.strip() if payload.descripcion else None,
        activa=True,
    )
    session.add(esp)
    session.flush()
    registrar_auditoria(
        session,
        usuario=actor,
        accion=AccionAuditoria.CREATE,
        tabla="especialidades",
        id_registro=esp.id,
        detalle=f"Alta de especialidad: {esp.nombre}",
        ip_origen=request.client.host if request.client else None,
    )
    session.commit()
    session.refresh(esp)
    return esp


@router.patch("/{especialidad_id}", response_model=EspecialidadRead)
def actualizar(
    especialidad_id: int,
    payload: EspecialidadUpdate,
    request: Request,
    session: Session = Depends(get_session),
    actor: Usuario = Depends(_admin),
):
    esp = session.get(Especialidad, especialidad_id)
    if not esp:
        raise HTTPException(404, "Especialidad no encontrada.")

    data = payload.model_dump(exclude_unset=True)
    nombre_anterior: Optional[str] = None

    if "nombre" in data and data["nombre"] is not None:
        nuevo_nombre = data["nombre"].strip()
        if nuevo_nombre.lower() != esp.nombre.lower():
            existente = _buscar_por_nombre_ci(session, nuevo_nombre)
            if existente is not None and existente.id != esp.id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Ya existe una especialidad con ese nombre.",
                )
        nombre_anterior = esp.nombre
        esp.nombre = nuevo_nombre

    if "descripcion" in data:
        esp.descripcion = data["descripcion"].strip() if data["descripcion"] else None
    if "activa" in data and data["activa"] is not None:
        esp.activa = data["activa"]

    session.add(esp)

    # Si se renombro, propagamos el cambio a los medicos que la tenian
    # asignada — la tabla medicos guarda el texto, no la FK, asi que el
    # catalogo y la tabla referenciadora deben quedar coherentes despues
    # del rename. Sin esto, los medicos veteranos "se quedarian" con el
    # nombre viejo y dejarian de cumplir la validacion.
    if nombre_anterior and nombre_anterior != esp.nombre:
        for col in (
            Medico.especialidad,
            Medico.especialidad_secundaria_1,
            Medico.especialidad_secundaria_2,
        ):
            for m in session.exec(select(Medico).where(col == nombre_anterior)).all():
                if m.especialidad == nombre_anterior:
                    m.especialidad = esp.nombre
                if m.especialidad_secundaria_1 == nombre_anterior:
                    m.especialidad_secundaria_1 = esp.nombre
                if m.especialidad_secundaria_2 == nombre_anterior:
                    m.especialidad_secundaria_2 = esp.nombre
                session.add(m)

    registrar_auditoria(
        session,
        usuario=actor,
        accion=AccionAuditoria.UPDATE,
        tabla="especialidades",
        id_registro=esp.id,
        detalle=(
            f"Update {list(data.keys())}"
            + (f" (rename '{nombre_anterior}' -> '{esp.nombre}')" if nombre_anterior else "")
        ),
        ip_origen=request.client.host if request.client else None,
    )
    session.commit()
    session.refresh(esp)
    return esp


@router.delete("/{especialidad_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar(
    especialidad_id: int,
    request: Request,
    session: Session = Depends(get_session),
    actor: Usuario = Depends(_admin),
):
    esp = session.get(Especialidad, especialidad_id)
    if not esp:
        raise HTTPException(404, "Especialidad no encontrada.")

    en_uso = _contar_medicos_que_usan(session, esp.nombre)
    if en_uso > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"No se puede eliminar: hay {en_uso} medico(s) asignado(s). "
                "Desactivela en lugar de eliminarla."
            ),
        )

    nombre = esp.nombre
    session.delete(esp)
    registrar_auditoria(
        session,
        usuario=actor,
        accion=AccionAuditoria.DELETE,
        tabla="especialidades",
        id_registro=especialidad_id,
        detalle=f"Baja de especialidad: {nombre}",
        ip_origen=request.client.host if request.client else None,
    )
    session.commit()
    return None
