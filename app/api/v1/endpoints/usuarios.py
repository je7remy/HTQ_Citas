"""Gestión de usuarios — restringido a administrador."""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.api.deps import require_roles
from app.core.security import hash_password
from app.db.session import get_session
from app.models import AccionAuditoria, RolUsuario, Usuario
from app.schemas import UsuarioCreate, UsuarioRead, UsuarioUpdate
from app.services.audit import registrar_auditoria

router = APIRouter(prefix="/usuarios", tags=["usuarios"])

_admin_only = require_roles(RolUsuario.admin)


@router.get("", response_model=list[UsuarioRead])
def listar(session: Session = Depends(get_session), _: Usuario = Depends(_admin_only)):
    return session.exec(select(Usuario).order_by(Usuario.id)).all()


@router.post("", response_model=UsuarioRead, status_code=status.HTTP_201_CREATED)
def crear(
    payload: UsuarioCreate,
    request: Request,
    session: Session = Depends(get_session),
    actor: Usuario = Depends(_admin_only),
):
    user = Usuario(
        nombre=payload.nombre,
        email=payload.email,
        password_hash=hash_password(payload.password),
        rol=payload.rol,
    )
    session.add(user)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=409, detail="El email ya está registrado.")

    registrar_auditoria(
        session,
        id_usuario=actor.id,
        accion=AccionAuditoria.CREATE,
        tabla="usuarios",
        id_registro=user.id,
        detalle=f"Alta usuario {user.email} rol={user.rol.value}",
        ip_origen=request.client.host if request.client else None,
    )
    session.commit()
    session.refresh(user)
    return user


@router.patch("/{user_id}", response_model=UsuarioRead)
def actualizar(
    user_id: int,
    payload: UsuarioUpdate,
    request: Request,
    session: Session = Depends(get_session),
    actor: Usuario = Depends(_admin_only),
):
    user = session.get(Usuario, user_id)
    if not user:
        raise HTTPException(404, "Usuario no encontrado.")
    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(user, k, v)
    session.add(user)
    registrar_auditoria(
        session,
        id_usuario=actor.id,
        accion=AccionAuditoria.UPDATE,
        tabla="usuarios",
        id_registro=user.id,
        detalle=f"Update {data}",
        ip_origen=request.client.host if request.client else None,
    )
    session.commit()
    session.refresh(user)
    return user


@router.delete("/{user_id}", status_code=204)
def eliminar(
    user_id: int,
    request: Request,
    session: Session = Depends(get_session),
    actor: Usuario = Depends(_admin_only),
):
    user = session.get(Usuario, user_id)
    if not user:
        raise HTTPException(404, "Usuario no encontrado.")
    # Soft delete por seguridad (preserva FK en auditoría/citas)
    user.activo = False
    session.add(user)
    registrar_auditoria(
        session,
        id_usuario=actor.id,
        accion=AccionAuditoria.DELETE,
        tabla="usuarios",
        id_registro=user.id,
        detalle=f"Soft delete {user.email}",
        ip_origen=request.client.host if request.client else None,
    )
    session.commit()
