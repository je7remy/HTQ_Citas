"""CRUD de citas + endpoint feed para FullCalendar.js.

CONTEXTO: módulo central de la operación diaria del HTQPJB. La secretaria
trabaja todo el día agendando y reprogramando citas; cualquier rotura
o latencia aquí impacta directamente la atención al paciente.

Cuatro flujos críticos:
  1. /citas (GET/POST/PATCH/DELETE) — CRUD base.
  2. /citas/agenda-extendida — alimenta la pantalla "Agenda del Día"
     con datos enriquecidos (paciente + médico + especialidad) en una
     sola query con triple JOIN.
  3. /citas/calendar — feed JSON con la forma exacta que espera
     FullCalendar.js (eventos con color por estado).
  4. PATCH con cambio de estado a 'cancelada' o reprogramación —
     comparten la validación de citas_service.validar_disponibilidad.

REGLA DE NEGOCIO IMPORTANTE: el médico NO puede crear/editar/cancelar
citas. Solo secretaria y admin (decisión del HTQPJB). El médico sí
puede ver su agenda y registrar consultas (módulo consultas).
"""
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.api.deps import require_roles
from app.core.datetime_utils import formatear_hora_12
from app.db.session import get_session
from app.models import AccionAuditoria, Cita, EstadoCita, Medico, Paciente, RolUsuario, Usuario
from app.schemas import (
    AgendaCitaItem,
    AgendaExtendidaResponse,
    CitaCreate,
    CitaRead,
    CitaUpdate,
)
from app.services.audit import registrar_auditoria
from app.services.citas_service import validar_disponibilidad

router = APIRouter(prefix="/citas", tags=["citas"])

# _staff: pueden CREAR y MODIFICAR citas (secretaria + admin).
# _any: pueden LEER citas (médico incluido — necesita ver su agenda).
_staff = require_roles(RolUsuario.secretaria, RolUsuario.admin)
_any = require_roles(RolUsuario.secretaria, RolUsuario.admin, RolUsuario.medico)


def _parse_fecha_param(valor: str | None) -> date | None:
    """Acepta 'YYYY-MM-DD' o ISO datetime y devuelve un date. None pasa intacto.

    Por qué tolera ambos formatos: la pantalla "Agenda del Día" del
    frontend manda a veces el datetime completo (ej. cuando viene de un
    rango de FullCalendar) y a veces solo la fecha. En vez de obligar
    al frontend a normalizar, lo hacemos aquí — menos código JS frágil.
    """
    if not valor:
        return None
    try:
        # Soporta tanto fecha ISO como datetime ISO ("2026-05-16T08:00")
        return datetime.fromisoformat(valor).date()
    except ValueError:
        try:
            return date.fromisoformat(valor)
        except ValueError as e:
            raise HTTPException(422, f"Fecha inválida: {valor!r}. Use formato ISO.") from e


def _construir_agenda_extendida(
    session: Session,
    *,
    id_medico: int | None,
    fecha_desde: date | None,
    fecha_hasta: date | None,
    estado: str | None,
    especialidad: str | None,
    busqueda_medico: str | None,
) -> AgendaExtendidaResponse:
    """Lógica común para agenda extendida (reusada por reportes PDF/Excel).

    Una sola query con triple JOIN (Cita ⋈ Paciente ⋈ Medico) en vez
    de N+1: con 50+ citas/día y red lenta del consultorio, traer cada
    paciente y médico aparte sería notable.

    Filtros aplicables (todos opcionales, se combinan con AND):
      - id_medico: cita.id_medico == N.
      - fecha_desde/fecha_hasta: rango inclusivo sobre cita.fecha.
      - estado: pendiente / atendida / cancelada / "todos" (alias de None).
      - especialidad: match exacto con Medico.especialidad.
      - busqueda_medico: ILIKE %patrón% sobre Medico.nombre (insensitive).

    OJO: extraído del endpoint para reutilizarlo desde reportes/agenda/pdf
    y /agenda/excel. Cambiar la firma rompe esos endpoints.
    """
    stmt = select(Cita, Paciente, Medico).where(
        Cita.id_paciente == Paciente.id,
        Cita.id_medico == Medico.id,
    )
    if fecha_desde:
        stmt = stmt.where(Cita.fecha >= fecha_desde)
    if fecha_hasta:
        stmt = stmt.where(Cita.fecha <= fecha_hasta)
    if id_medico:
        stmt = stmt.where(Cita.id_medico == id_medico)
    if estado and estado != "todos":
        try:
            estado_enum = EstadoCita(estado)
        except ValueError as e:
            raise HTTPException(422, f"Estado inválido: {estado!r}.") from e
        stmt = stmt.where(Cita.estado == estado_enum)
    if especialidad:
        stmt = stmt.where(Medico.especialidad == especialidad)
    if busqueda_medico:
        patron = f"%{busqueda_medico.strip()}%"
        stmt = stmt.where(Medico.nombre.ilike(patron))

    rows = session.exec(stmt.order_by(Cita.fecha, Cita.hora)).all()

    citas = [
        AgendaCitaItem(
            id=c.id,
            fecha=c.fecha,
            hora=c.hora,
            hora_12h=formatear_hora_12(c.hora),
            estado=c.estado,
            motivo=c.motivo,
            id_paciente=p.id,
            paciente_nombre=f"{p.nombre} {p.apellidos}",
            paciente_cedula=p.cedula,
            id_medico=m.id,
            medico_nombre=m.nombre,
            medico_especialidad=m.especialidad,
        )
        for c, p, m in rows
    ]
    return AgendaExtendidaResponse(
        total=len(citas),
        pendientes=sum(1 for x in citas if x.estado == EstadoCita.pendiente),
        atendidas=sum(1 for x in citas if x.estado == EstadoCita.atendida),
        canceladas=sum(1 for x in citas if x.estado == EstadoCita.cancelada),
        citas=citas,
    )


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


@router.get("/agenda-extendida", response_model=AgendaExtendidaResponse)
def agenda_extendida(
    id_medico: int | None = None,
    fecha_desde: str | None = Query(None, description="ISO date o datetime"),
    fecha_hasta: str | None = Query(None, description="ISO date o datetime"),
    estado: str | None = Query(None, description="pendiente|atendida|cancelada|todos"),
    especialidad: str | None = None,
    busqueda_medico: str | None = Query(None, description="Coincidencia parcial por nombre"),
    session: Session = Depends(get_session),
    _: Usuario = Depends(_staff),
):
    """Agenda detallada del día/rango para la secretaria (CU-12 extendido).

    Devuelve citas enriquecidas con paciente, médico y especialidad, además
    de conteos por estado. Acceso restringido a secretaria/admin.
    """
    return _construir_agenda_extendida(
        session,
        id_medico=id_medico,
        fecha_desde=_parse_fecha_param(fecha_desde),
        fecha_hasta=_parse_fecha_param(fecha_hasta),
        estado=estado,
        especialidad=especialidad,
        busqueda_medico=busqueda_medico,
    )


@router.get("/calendar")
def feed_calendar(
    start: date = Query(..., description="ISO date — inicio del rango FullCalendar"),
    end: date = Query(..., description="ISO date — fin del rango FullCalendar"),
    id_medico: int | None = None,
    session: Session = Depends(get_session),
    _: Usuario = Depends(_any),
):
    """Devuelve eventos en formato FullCalendar.

    El shape del JSON está dictado por la API de FullCalendar.js (la
    librería del calendario en el frontend). NO modificar campos a menos
    que también se actualice el código de calendar.html — los eventos
    se renderizan automáticamente leyendo `id`, `title`, `start`, `color`
    y `extendedProps`.

    `start` debe ser ISO 8601 con T entre fecha y hora; no usar espacio
    o FullCalendar lo descarta silenciosamente.

    Paleta:
      - Pendiente: azul (#2563eb) — destaca lo que falta hacer.
      - Atendida: verde (#16a34a) — confirma completitud.
      - Cancelada: gris (#9ca3af) — apagado, no llama la atención.
    """
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
    # Validación en dos capas:
    # 1) validar_disponibilidad() chequea reglas de negocio y devuelve
    #    errores semánticos (E-005, E-006) en formato HTTP 409/422 que
    #    el frontend entiende.
    # 2) Si dos secretarias agendan EN EL MISMO INSTANTE el mismo slot
    #    y ambas validaciones pasan (race condition), el UNIQUE parcial
    #    de la BD garantiza que solo una INSERT lo logre — la otra
    #    truena con IntegrityError y la traducimos a 409.
    # Sin la capa 2, podrían crearse dos citas duplicadas en burst.
    validar_disponibilidad(
        session,
        id_medico=payload.id_medico,
        id_paciente=payload.id_paciente,
        fecha=payload.fecha,
        hora=payload.hora,
    )
    # id_secretaria se toma del usuario autenticado, NUNCA del payload.
    # Si el campo llegara por payload, cualquier secretaria podría agendar
    # "a nombre de" otra y desviar la auditoría.
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
    # Cubre dos casos en un solo endpoint:
    #   - Reprogramar: viene fecha y/o hora nueva → revalidar slot.
    #   - Cambiar estado/motivo: NO requiere revalidar (no toca el slot).
    # exclude_unset=True hace que solo lleguen los campos que el cliente
    # mandó, para no resetear los demás a None por accidente.
    cita = session.get(Cita, cita_id)
    if not cita:
        raise HTTPException(404, "Cita no encontrada.")

    data = payload.model_dump(exclude_unset=True)

    # Si cambia fecha/hora, revalidar disponibilidad.
    # `excluir_cita_id=cita.id` evita que validar_disponibilidad rechace
    # la reprogramación tomándose a sí misma como "slot ocupado".
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
    """No elimina físicamente — marca como cancelada (preserva historial).

    IMPORTANTE: aunque el verbo HTTP sea DELETE, la operación interna es
    UPDATE (estado='cancelada'). El frontend usa DELETE por convención
    REST y porque deja claro que el slot se libera.

    Razones para NO borrar físicamente:
    1. Auditoría legal (Ley 172-13) exige preservar la historia.
    2. Si se borra y luego el paciente reclama "yo tenía cita el día X",
       no hay rastro.
    3. Los reportes admin necesitan el conteo de canceladas.

    El índice único parcial de la BD libera el slot automáticamente al
    cambiar estado → 'cancelada' (no aplica WHERE estado<>'cancelada').
    """
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
