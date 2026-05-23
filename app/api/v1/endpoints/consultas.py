"""Módulo médico: agenda diaria + observaciones de consultas.

CONTEXTO: este es EL módulo del rol médico. Aquí ve sus citas del día
y registra el resultado de cada atención. Las reglas son estrictas:
  - El médico solo puede registrar consultas de SUS PROPIAS citas
    (chequeado en runtime — el JWT no basta).
  - No se puede registrar consulta antes del horario de la cita (evita
    falsos atendimientos antes de que el paciente llegue).
  - Una cita solo admite UNA consulta (UNIQUE id_cita).
  - Registrar consulta cambia el estado de la cita a 'atendida' en la
    misma transacción.

El admin puede registrar consultas también (caso atípico: corregir
un olvido del médico), pero debe pasar id_medico explícito en el
payload — no se infiere de su sesión.
"""
from datetime import date as date_type
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.api.deps import require_roles
from app.core.datetime_utils import TZ_DOMINICANA, ahora_local
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
    # Resuelve el Medico vinculado a un Usuario.
    # Admin NO tiene perfil de médico — fallamos explícito para que el
    # endpoint exija id_medico en el payload (caso atípico de admin
    # registrando consulta por médico).
    # Médico sin Medico vinculado tampoco puede actuar: configuración
    # incompleta del admin (creó el Usuario pero no el Medico).
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
    # Validación temporal: comparamos contra el datetime completo en TZ
    # dominicana. Permitir consulta antes de la cita programada llevaría
    # a registros "atendida" con horas físicamente imposibles (el médico
    # no puede haber visto al paciente que aún no llega).
    cita = session.get(Cita, payload.id_cita)
    if not cita:
        raise HTTPException(404, "Cita no encontrada.")

    fecha_hora_cita = datetime.combine(cita.fecha, cita.hora, tzinfo=TZ_DOMINICANA)
    if ahora_local() < fecha_hora_cita:
        raise HTTPException(
            400,
            "No se puede registrar la consulta antes del horario programado de la cita.",
        )

    # Defensa principal del rol médico: solo puede tocar SUS citas.
    # Admin se salta este check porque puede actuar en nombre de cualquier
    # médico (rara vez — corrección de olvidos).
    if user.rol == RolUsuario.medico:
        medico = _medico_del_usuario(session, user)
        if cita.id_medico != medico.id:
            raise HTTPException(403, "Solo puede registrar consultas de sus propias citas.")

    consulta = Consulta(
        id_cita=payload.id_cita,
        motivo_consulta=payload.motivo_consulta,
        examen_fisico=payload.examen_fisico,
        condicion_principal=payload.condicion_principal,
        condiciones_secundarias=payload.condiciones_secundarias,
        tratamiento=payload.tratamiento,
    )
    session.add(consulta)

    # Cambio de estado de la cita en la MISMA transacción: si falla el
    # INSERT de consulta (UNIQUE id_cita ya tomado), el rollback deshace
    # también el cambio de estado — la cita queda como pendiente.
    cita.estado = EstadoCita.atendida
    session.add(cita)

    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        # UNIQUE id_cita activado: el médico ya registró esta consulta antes.
        # Probablemente doble clic en el botón de guardar.
        raise HTTPException(409, "Esta cita ya tiene una consulta registrada.")

    registrar_auditoria(
        session,
        usuario=user,
        accion=AccionAuditoria.CREATE,
        tabla="consultas",
        id_registro=consulta.id,
        detalle=f"Consulta cita={payload.id_cita}",
        ip_origen=request.client.host if request.client else None,
    )
    session.commit()
    session.refresh(consulta)
    return consulta
