"""Lógica de negocio para citas: validación de disponibilidad.

CONTEXTO: extraído del endpoint de citas para que la validación sea
reutilizable entre POST /citas (crear) y PATCH /citas/{id} (reprogramar).
Centraliza los códigos de error E-005 (horario ocupado) y E-006 (fuera
de horario del médico) de la tesis (Anexo P).

CUIDADO: TODO endpoint que cree o reprograme citas DEBE pasar por aquí.
Saltarse esta validación deja la puerta abierta a doble-booking en
condición de carrera (la BD seguiría cubriendo, pero con un IntegrityError
crudo que el frontend no sabe traducir).
"""
from datetime import date, datetime, time

from fastapi import HTTPException
from sqlmodel import Session, select

from app.core.datetime_utils import TZ_DOMINICANA, ahora_local
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
    - La fecha+hora completa de la cita NO es en el pasado (compara contra
      ahora_local() — nunca solo la hora del día).
    - La hora cae dentro de un horario activo del médico para ese día.
    - No hay otra cita pendiente/atendida en el mismo slot (defensa en profundidad
      sobre la restricción UNIQUE de la BD).
    """
    medico = session.get(Medico, id_medico)
    if not medico or not medico.activo:
        raise HTTPException(404, "Médico no encontrado o inactivo.")

    if not session.get(Paciente, id_paciente):
        raise HTTPException(404, "Paciente no encontrado.")

    # Comparar SIEMPRE fecha+hora completa. Comparar solo `hora` rechazaría
    # incorrectamente, a las 11 PM, una cita para mañana a las 09 AM
    # (porque 09:00 < 23:00) aunque ese instante todavía es futuro.
    fecha_hora_cita = datetime.combine(fecha, hora, tzinfo=TZ_DOMINICANA)
    if fecha_hora_cita < ahora_local():
        raise HTTPException(
            409, "No se puede crear una cita en una fecha/hora ya pasada."
        )

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
