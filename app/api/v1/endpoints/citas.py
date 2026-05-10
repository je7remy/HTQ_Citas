"""CRUD de citas + endpoint feed para FullCalendar.js."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.api.deps import require_roles
from app.db.session import get_session
from app.models import AccionAuditoria, Cita, EstadoCita, Medico, Paciente, RolUsuario, Usuario
from app.schemas import CitaCreate, CitaRead, CitaUpdate
from app.services.audit import registrar_auditoria
from app.services.citas_service import validar_disponibilidad

router = APIRouter(prefix="/citas", tags=["citas"])

_staff = require_roles(RolUsuario.secretaria, RolUsuario.admin)
_any = require_roles(RolUsuario.secretaria, RolUsuario.admin, RolUsuario.medico)


@router.get("", response_model=list[CitaRead])
def listar(
    desde: date | None = None,
    hasta: date | None = None,
    id_medico: int | None = None,
    estado: EstadoCita | None = None,
    session: Session = Depends(get_session),
    _: Usuario = Depends(_any),
):
    stmt = select(Cita)
    if desde:
        stmt = stmt.where(Cita.fecha >= desde)
    if hasta:
        stmt = stmt.where(Cita.fecha <= hasta)
    if id_medico:
        stmt = stmt.where(Cita.id_medico == id_medico)
    if estado:
        stmt = stmt.where(Cita.estado == estado)
    return session.exec(stmt.order_by(Cita.fecha, Cita.hora)).all()


@router.get("/calendar")
def feed_calendar(
    start: date = Query(..., description="ISO date — inicio del rango FullCalendar"),
    end: date = Query(..., description="ISO date — fin del rango FullCalendar"),
    id_medico: int | None = None,
    session: Session = Depends(get_session),
    _: Usuario = Depends(_any),
):
    """Devuelve eventos en formato FullCalendar."""
    stmt = select(Cita, Paciente, Medico).where(
        Cita.id_paciente == Paciente.id,
        Cita.id_medico == Medico.id,
        Cita.fecha >= start,
        Cita.fecha <= end,
    )
    if id_medico:
        stmt = stmt.where(Cita.id_medico == id_medico)
    rows = session.exec(stmt).all()

    color_por_estado = {
        EstadoCita.pendiente: "#2563eb",
        EstadoCita.atendida: "#16a34a",
        EstadoCita.cancelada: "#9ca3af",
    }
    return [
        {
            "id": c.id,
            "title": f"{p.nombre} {p.apellidos} — {m.nombre}",
            "start": f"{c.fecha.isoformat()}T{c.hora.isoformat()}",
            "color": color_por_estado.get(c.estado, "#2563eb"),
            "extendedProps": {
                "estado": c.estado.value,
                "motivo": c.motivo,
                "id_medico": c.id_medico,
                "id_paciente": c.id_paciente,
            },
        }
        for c, p, m in rows
    ]


@router.post("", response_model=CitaRead, status_code=status.HTTP_201_CREATED)
def crear(
    payload: CitaCreate,
    request: Request,
    session: Session = Depends(get_session),
    actor: Usuario = Depends(_staff),
):
    validar_disponibilidad(
        session,
        id_medico=payload.id_medico,
        id_paciente=payload.id_paciente,
        fecha=payload.fecha,
        hora=payload.hora,
    )
    cita = Cita(
        id_paciente=payload.id_paciente,
        id_medico=payload.id_medico,
        fecha=payload.fecha,
        hora=payload.hora,
        motivo=payload.motivo,
        id_secretaria=actor.id,
    )
    session.add(cita)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        # Defensa contra carreras: la UNIQUE de la BD es la última línea
        raise HTTPException(409, "E-005: Horario ocupado.")

    registrar_auditoria(
        session,
        usuario=actor,
        accion=AccionAuditoria.CREATE,
        tabla="citas",
        id_registro=cita.id,
        detalle=f"Cita medico={cita.id_medico} {cita.fecha} {cita.hora}",
        ip_origen=request.client.host if request.client else None,
    )
    session.commit()
    session.refresh(cita)
    return cita


@router.patch("/{cita_id}", response_model=CitaRead)
def actualizar(
    cita_id: int,
    payload: CitaUpdate,
    request: Request,
    session: Session = Depends(get_session),
    actor: Usuario = Depends(_staff),
):
    cita = session.get(Cita, cita_id)
    if not cita:
        raise HTTPException(404, "Cita no encontrada.")

    data = payload.model_dump(exclude_unset=True)

    # Si cambia fecha/hora, revalidar disponibilidad
    if "fecha" in data or "hora" in data:
        nueva_fecha = data.get("fecha", cita.fecha)
        nueva_hora = data.get("hora", cita.hora)
        validar_disponibilidad(
            session,
            id_medico=cita.id_medico,
            id_paciente=cita.id_paciente,
            fecha=nueva_fecha,
            hora=nueva_hora,
            excluir_cita_id=cita.id,
        )

    for k, v in data.items():
        setattr(cita, k, v)
    session.add(cita)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        raise HTTPException(409, "E-005: Horario ocupado.")

    registrar_auditoria(
        session,
        usuario=actor,
        accion=AccionAuditoria.UPDATE,
        tabla="citas",
        id_registro=cita.id,
        detalle=f"Update {list(data.keys())}",
        ip_origen=request.client.host if request.client else None,
    )
    session.commit()
    session.refresh(cita)
    return cita


@router.delete("/{cita_id}", status_code=204)
def cancelar(
    cita_id: int,
    request: Request,
    session: Session = Depends(get_session),
    actor: Usuario = Depends(_staff),
):
    """No elimina físicamente — marca como cancelada (preserva historial)."""
    cita = session.get(Cita, cita_id)
    if not cita:
        raise HTTPException(404, "Cita no encontrada.")
    cita.estado = EstadoCita.cancelada
    session.add(cita)
    registrar_auditoria(
        session,
        usuario=actor,
        accion=AccionAuditoria.DELETE,
        tabla="citas",
        id_registro=cita.id,
        detalle="Cancelación de cita",
        ip_origen=request.client.host if request.client else None,
    )
    session.commit()
