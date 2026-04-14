"""Lógica de negocio para citas: validación de disponibilidad."""
from datetime import date, time

from fastapi import HTTPException
from sqlmodel import Session, select

from app.models import Cita, EstadoCita, Horario, Medico, Paciente


def validar_disponibilidad(
    session: Session,
    *,
    id_medico: int,
    id_paciente: int,
    fecha: date,
    hora: time,
    excluir_cita_id: int | None = None,
) -> None:
    """Valida que la cita pueda crearse:
    - Médico existe y está activo.
    - Paciente existe.
    - La hora cae dentro de un horario activo del médico para ese día.
    - No hay otra cita pendiente/atendida en el mismo slot (defensa en profundidad
      sobre la restricción UNIQUE de la BD).
    """
    medico = session.get(Medico, id_medico)
    if not medico or not medico.activo:
        raise HTTPException(404, "Médico no encontrado o inactivo.")

    if not session.get(Paciente, id_paciente):
        raise HTTPException(404, "Paciente no encontrado.")

    # ISO weekday: lunes=1 ... domingo=7 (coincide con la convención de la tesis)
    dia_semana = fecha.isoweekday()
    horarios = session.exec(
        select(Horario).where(
            Horario.id_medico == id_medico,
            Horario.activo == True,  # noqa: E712
            Horario.dia_semana == dia_semana,
        )
    ).all()
    if not horarios:
        raise HTTPException(409, "E-006: El médico no atiende ese día.")

    if not any(h.hora_inicio <= hora < h.hora_fin for h in horarios):
        raise HTTPException(409, "E-006: La hora está fuera del horario de atención del médico.")

    stmt = select(Cita).where(
        Cita.id_medico == id_medico,
        Cita.fecha == fecha,
        Cita.hora == hora,
        Cita.estado != EstadoCita.cancelada,
    )
    if excluir_cita_id:
        stmt = stmt.where(Cita.id != excluir_cita_id)
    if session.exec(stmt).first():
        raise HTTPException(409, "E-005: Horario ocupado.")
