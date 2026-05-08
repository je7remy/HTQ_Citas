"""CRUD de médicos y gestión de horarios."""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlmodel import Session, select

from app.api.deps import require_roles
from app.core.security import hash_password
from app.db.session import get_session
from app.models import AccionAuditoria, Horario, Medico, RolUsuario, Usuario
from app.schemas import (
    HorarioCreate,
    HorarioRead,
    MedicoConUsuarioCreate,
    MedicoCreate,
    MedicoRead,
    MedicoUpdate,
)
from app.services.audit import registrar_auditoria

router = APIRouter(prefix="/medicos", tags=["medicos"])

_admin = require_roles(RolUsuario.admin)
_any = require_roles(RolUsuario.secretaria, RolUsuario.admin, RolUsuario.medico)


# ---------- Médicos ----------
@router.get("", response_model=list[MedicoRead])
def listar(session: Session = Depends(get_session), _: Usuario = Depends(_any)):
    return session.exec(select(Medico).where(Medico.activo == True).order_by(Medico.nombre)).all()  # noqa: E712


@router.post("", response_model=MedicoRead, status_code=status.HTTP_201_CREATED)
def crear(
    payload: MedicoCreate,
    request: Request,
    session: Session = Depends(get_session),
    actor: Usuario = Depends(_admin),
):
    if payload.id_usuario is not None:
        u = session.get(Usuario, payload.id_usuario)
        if not u or u.rol != RolUsuario.medico:
            raise HTTPException(
                422,
                "El usuario seleccionado no es válido o ya está vinculado a otro perfil de médico.",
            )
        existing = session.exec(
            select(Medico).where(Medico.id_usuario == payload.id_usuario)
        ).first()
        if existing:
            raise HTTPException(
                422,
                "El usuario seleccionado no es válido o ya está vinculado a otro perfil de médico.",
            )
    m = Medico(**payload.model_dump())
    session.add(m)
    session.flush()
    registrar_auditoria(
        session,
        id_usuario=actor.id,
        accion=AccionAuditoria.CREATE,
        tabla="medicos",
        id_registro=m.id,
        detalle=f"Alta medico {m.nombre} ({m.especialidad})",
        ip_origen=request.client.host if request.client else None,
    )
    session.commit()
    session.refresh(m)
    return m


@router.post("/con-usuario", response_model=MedicoRead, status_code=status.HTTP_201_CREATED)
def crear_con_usuario(
    payload: MedicoConUsuarioCreate,
    request: Request,
    session: Session = Depends(get_session),
    actor: Usuario = Depends(_admin),
):
    existing = session.exec(select(Usuario).where(Usuario.email == payload.usuario.email)).first()
    if existing:
        raise HTTPException(409, "El email ya está registrado.")

    u = Usuario(
        nombre=payload.usuario.nombre,
        email=payload.usuario.email,
        password_hash=hash_password(payload.usuario.password),
        rol=RolUsuario.medico,
    )
    session.add(u)
    session.flush()

    m = Medico(
        id_usuario=u.id,
        nombre=payload.medico.nombre,
        especialidad=payload.medico.especialidad,
        telefono=payload.medico.telefono,
    )
    session.add(m)
    session.flush()

    registrar_auditoria(
        session,
        id_usuario=actor.id,
        accion=AccionAuditoria.CREATE,
        tabla="medicos",
        id_registro=m.id,
        detalle=f"Alta medico con usuario {u.email} ({m.especialidad})",
        ip_origen=request.client.host if request.client else None,
    )
    session.commit()
    session.refresh(m)
    return m


@router.patch("/{medico_id}", response_model=MedicoRead)
def actualizar(
    medico_id: int,
    payload: MedicoUpdate,
    request: Request,
    session: Session = Depends(get_session),
    actor: Usuario = Depends(_admin),
):
    m = session.get(Medico, medico_id)
    if not m:
        raise HTTPException(404, "Médico no encontrado.")
    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(m, k, v)
    session.add(m)
    registrar_auditoria(
        session,
        id_usuario=actor.id,
        accion=AccionAuditoria.UPDATE,
        tabla="medicos",
        id_registro=m.id,
        detalle=f"Update {list(data.keys())}",
        ip_origen=request.client.host if request.client else None,
    )
    session.commit()
    session.refresh(m)
    return m


# ---------- Horarios ----------
@router.get("/{medico_id}/horarios", response_model=list[HorarioRead])
def horarios_de_medico(
    medico_id: int,
    session: Session = Depends(get_session),
    _: Usuario = Depends(_any),
):
    return session.exec(
        select(Horario).where(Horario.id_medico == medico_id, Horario.activo == True)  # noqa: E712
    ).all()


@router.post("/{medico_id}/horarios", response_model=HorarioRead, status_code=201)
def crear_horario(
    medico_id: int,
    payload: HorarioCreate,
    request: Request,
    session: Session = Depends(get_session),
    actor: Usuario = Depends(_admin),
):
    if payload.id_medico != medico_id:
        raise HTTPException(400, "id_medico del cuerpo no coincide con la ruta.")
    if not session.get(Medico, medico_id):
        raise HTTPException(404, "Médico no encontrado.")
    h = Horario(**payload.model_dump())
    session.add(h)
    session.flush()
    registrar_auditoria(
        session,
        id_usuario=actor.id,
        accion=AccionAuditoria.CREATE,
        tabla="horarios",
        id_registro=h.id,
        detalle=f"Horario medico={medico_id} dia={h.dia_semana} {h.hora_inicio}-{h.hora_fin}",
        ip_origen=request.client.host if request.client else None,
    )
    session.commit()
    session.refresh(h)
    return h


@router.delete("/horarios/{horario_id}", status_code=204)
def eliminar_horario(
    horario_id: int,
    request: Request,
    session: Session = Depends(get_session),
    actor: Usuario = Depends(_admin),
):
    h = session.get(Horario, horario_id)
    if not h:
        raise HTTPException(404, "Horario no encontrado.")
    h.activo = False
    session.add(h)
    registrar_auditoria(
        session,
        id_usuario=actor.id,
        accion=AccionAuditoria.DELETE,
        tabla="horarios",
        id_registro=horario_id,
        detalle="Soft delete horario",
        ip_origen=request.client.host if request.client else None,
    )
    session.commit()
