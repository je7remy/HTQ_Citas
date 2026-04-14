"""CRUD de pacientes — secretaria y admin."""
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, or_, select

from app.api.deps import require_roles
from app.db.session import get_session
from app.models import AccionAuditoria, Paciente, RolUsuario, Usuario
from app.schemas import PacienteCreate, PacienteRead, PacienteUpdate
from app.services.audit import registrar_auditoria

router = APIRouter(prefix="/pacientes", tags=["pacientes"])

_staff = require_roles(RolUsuario.secretaria, RolUsuario.admin)
_any_user = require_roles(RolUsuario.secretaria, RolUsuario.admin, RolUsuario.medico)


@router.get("", response_model=list[PacienteRead])
def listar(
    q: str | None = Query(default=None, description="Búsqueda por cédula/nombre/apellidos"),
    limit: int = Query(default=50, le=200),
    offset: int = 0,
    session: Session = Depends(get_session),
    _: Usuario = Depends(_any_user),
):
    stmt = select(Paciente)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(Paciente.cedula.like(like), Paciente.nombre.ilike(like), Paciente.apellidos.ilike(like))
        )
    stmt = stmt.order_by(Paciente.apellidos).offset(offset).limit(limit)
    return session.exec(stmt).all()


@router.get("/{paciente_id}", response_model=PacienteRead)
def obtener(paciente_id: int, session: Session = Depends(get_session), _: Usuario = Depends(_any_user)):
    p = session.get(Paciente, paciente_id)
    if not p:
        raise HTTPException(404, "Paciente no encontrado.")
    return p


@router.post("", response_model=PacienteRead, status_code=status.HTTP_201_CREATED)
def crear(
    payload: PacienteCreate,
    request: Request,
    session: Session = Depends(get_session),
    actor: Usuario = Depends(_staff),
):
    p = Paciente(**payload.model_dump())
    session.add(p)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        # E-007: cédula duplicada
        raise HTTPException(409, "E-007: La cédula ingresada ya está registrada.")

    registrar_auditoria(
        session,
        id_usuario=actor.id,
        accion=AccionAuditoria.CREATE,
        tabla="pacientes",
        id_registro=p.id,
        detalle=f"Alta paciente cedula={p.cedula}",
        ip_origen=request.client.host if request.client else None,
    )
    session.commit()
    session.refresh(p)
    return p


@router.patch("/{paciente_id}", response_model=PacienteRead)
def actualizar(
    paciente_id: int,
    payload: PacienteUpdate,
    request: Request,
    session: Session = Depends(get_session),
    actor: Usuario = Depends(_staff),
):
    p = session.get(Paciente, paciente_id)
    if not p:
        raise HTTPException(404, "Paciente no encontrado.")
    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(p, k, v)
    session.add(p)
    registrar_auditoria(
        session,
        id_usuario=actor.id,
        accion=AccionAuditoria.UPDATE,
        tabla="pacientes",
        id_registro=p.id,
        detalle=f"Update {list(data.keys())}",
        ip_origen=request.client.host if request.client else None,
    )
    session.commit()
    session.refresh(p)
    return p


@router.delete("/{paciente_id}", status_code=204)
def eliminar(
    paciente_id: int,
    request: Request,
    session: Session = Depends(get_session),
    actor: Usuario = Depends(_staff),
):
    p = session.get(Paciente, paciente_id)
    if not p:
        raise HTTPException(404, "Paciente no encontrado.")
    session.delete(p)
    registrar_auditoria(
        session,
        id_usuario=actor.id,
        accion=AccionAuditoria.DELETE,
        tabla="pacientes",
        id_registro=paciente_id,
        detalle=f"Eliminado cedula={p.cedula}",
        ip_origen=request.client.host if request.client else None,
    )
    session.commit()
