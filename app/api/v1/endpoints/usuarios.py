"""Gestión de usuarios — restringido a administrador.

CONTEXTO: solo el admin entra a este módulo. Sirve para crear cuentas
nuevas (secretarias, médicos, otros admins), resetear contraseñas
olvidadas y desactivar usuarios que ya no trabajan en el hospital.

REGLAS:
  - DELETE es SOFT (activo=False) — preserva auditoría y referencias.
  - PATCH /password no requiere conocer la password anterior (es
    "reset por admin", no "cambio por usuario"). En la auditoría se
    registra "Reset password de X" SIN incluir la nueva password.
  - filtro sin_perfil_medico se usa en la pantalla de "crear médico":
    el admin escoge primero un Usuario con rol=medico que aún NO esté
    vinculado a ningún Medico, evitando duplicar perfiles.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.api.deps import require_roles
from app.core.security import hash_password
from app.db.session import get_session
from app.models import AccionAuditoria, Medico, RolUsuario, Usuario
from app.schemas import PasswordReset, UsuarioCreate, UsuarioRead, UsuarioUpdate
from app.services.audit import registrar_auditoria

router = APIRouter(prefix="/usuarios", tags=["usuarios"])

_admin_only = require_roles(RolUsuario.admin)


@router.get("", response_model=list[UsuarioRead])
def listar(
    rol: Optional[RolUsuario] = Query(default=None),
    sin_perfil_medico: bool = Query(default=False),
    session: Session = Depends(get_session),
    _: Usuario = Depends(_admin_only),
):
    # `sin_perfil_medico` con subquery NOT IN: devuelve usuarios que aún
    # no aparecen en `medicos.id_usuario`. Lo usa la pantalla de "crear
    # médico" para poblar el dropdown de Usuario a vincular, evitando
    # ofrecer cuentas ya asignadas (que crearían inconsistencia 1-a-1).
    # E711 está deshabilitado a propósito: SQLAlchemy NECESITA `!= None`
    # para generar `IS NOT NULL` en SQL — un `is not None` haría compare
    # en Python sin tocar la query.
    stmt = select(Usuario).order_by(Usuario.id)
    if rol:
        stmt = stmt.where(Usuario.rol == rol)
    if sin_perfil_medico:
        linked_subq = select(Medico.id_usuario).where(Medico.id_usuario != None)  # noqa: E711
        stmt = stmt.where(Usuario.id.not_in(linked_subq))
    return session.exec(stmt).all()


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
        usuario=actor,
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
        usuario=actor,
        accion=AccionAuditoria.UPDATE,
        tabla="usuarios",
        id_registro=user.id,
        detalle=f"Update {data}",
        ip_origen=request.client.host if request.client else None,
    )
    session.commit()
    session.refresh(user)
    return user


@router.patch("/{user_id}/password", response_model=UsuarioRead)
def cambiar_password(
    user_id: int,
    payload: PasswordReset,
    request: Request,
    session: Session = Depends(get_session),
    actor: Usuario = Depends(_admin_only),
):
    """Reset de contraseña realizado por un administrador.

    El admin no necesita conocer la contraseña anterior. Se reutiliza la
    política y la función de hashing existentes; el detalle de auditoría
    nunca incluye la contraseña ni su hash.

    IMPORTANTE: el detalle de auditoría dice "Reset password de {email}"
    — NO incluir nunca el valor nuevo ni el hash. Si un día se loggea
    esta cadena en plano (Sentry, journald), queda escrita la contraseña.
    """
    user = session.get(Usuario, user_id)
    if not user:
        raise HTTPException(404, "Usuario no encontrado.")
    user.password_hash = hash_password(payload.nueva_password)
    session.add(user)
    registrar_auditoria(
        session,
        usuario=actor,
        accion=AccionAuditoria.UPDATE,
        tabla="usuarios",
        id_registro=user.id,
        detalle=f"Reset password de {user.email}",
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
    # Soft delete por seguridad (preserva FK en auditoría/citas).
    # Si se hiciera DELETE físico:
    #   - Las FK de citas, auditoría y consultas con id_usuario NOT NULL
    #     truncarían en cascada o lanzarían IntegrityError 500.
    #   - Se perdería la trazabilidad histórica que pide la Ley 172-13.
    # `activo=False` mantiene el registro pero impide login.
    user.activo = False
    session.add(user)
    registrar_auditoria(
        session,
        usuario=actor,
        accion=AccionAuditoria.DELETE,
        tabla="usuarios",
        id_registro=user.id,
        detalle=f"Soft delete {user.email}",
        ip_origen=request.client.host if request.client else None,
    )
    session.commit()
