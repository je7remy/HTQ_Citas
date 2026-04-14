"""Módulo médico: agenda diaria + observaciones de consultas."""
from datetime import date as date_type

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.api.deps import require_roles
from app.db.session import get_session
from app.models import (
    AccionAuditoria,
    Cita,
    Consulta,
    EstadoCita,
    Medico,
    RolUsuario,
    Usuario,
)
from app.schemas import CitaRead, ConsultaCreate, ConsultaRead
from app.services.audit import registrar_auditoria

router = APIRouter(prefix="/consultas", tags=["consultas"])

_medico_only = require_roles(RolUsuario.medico, RolUsuario.admin)


def _medico_del_usuario(session: Session, user: Usuario) -> Medico:
    if user.rol == RolUsuario.admin:
        raise HTTPException(400, "Indique id_medico explícitamente para admin.")
    m = session.exec(select(Medico).where(Medico.id_usuario == user.id)).first()
    if not m:
        raise HTTPException(404, "El usuario no está vinculado a ningún médico.")
    return m


@router.get("/agenda", response_model=list[CitaRead])
def agenda_diaria(
    fecha: date_type | None = None,
    session: Session = Depends(get_session),
    user: Usuario = Depends(_medico_only),
):
    """Agenda del día para el médico autenticado."""
    fecha = fecha or date_type.today()
    medico = _medico_del_usuario(session, user)
    return session.exec(
        select(Cita)
        .where(Cita.id_medico == medico.id, Cita.fecha == fecha)
        .order_by(Cita.hora)
    ).all()


@router.post("", response_model=ConsultaRead, status_code=status.HTTP_201_CREATED)
def registrar_consulta(
    payload: ConsultaCreate,
    request: Request,
    session: Session = Depends(get_session),
    user: Usuario = Depends(_medico_only),
):
    cita = session.get(Cita, payload.id_cita)
    if not cita:
        raise HTTPException(404, "Cita no encontrada.")

    # Si es médico (no admin), debe ser dueño de la cita
    if user.rol == RolUsuario.medico:
        medico = _medico_del_usuario(session, user)
        if cita.id_medico != medico.id:
            raise HTTPException(403, "Solo puede registrar consultas de sus propias citas.")

    consulta = Consulta(id_cita=payload.id_cita, observaciones=payload.observaciones)
    session.add(consulta)

    cita.estado = EstadoCita.atendida
    session.add(cita)

    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        raise HTTPException(409, "Esta cita ya tiene una consulta registrada.")

    registrar_auditoria(
        session,
        id_usuario=user.id,
        accion=AccionAuditoria.CREATE,
        tabla="consultas",
        id_registro=consulta.id,
        detalle=f"Consulta cita={payload.id_cita}",
        ip_origen=request.client.host if request.client else None,
    )
    session.commit()
    session.refresh(consulta)
    return consulta
