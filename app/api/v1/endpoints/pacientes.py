"""CRUD de pacientes — secretaria y admin.

CONTEXTO: el paciente es la entidad raíz del flujo clínico. Los IDs
de paciente terminan referenciados desde citas → consultas, así que
cualquier cambio aquí impacta historial e indicadores.

OJO: a diferencia de citas/usuarios, el DELETE de paciente es FÍSICO
(session.delete). El supuesto es que solo se borra un paciente recién
registrado sin citas (ej. típo en cédula). Si el paciente ya tiene
citas, la FK truena con IntegrityError 500 sin manejo elegante — el
front debería prevenirlo, pero conviene revisar más adelante.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, or_, select

from app.api.deps import require_roles
from app.core.datetime_utils import formatear_hora_12
from app.db.session import get_session
from app.models import AccionAuditoria, Cita, Consulta, EstadoCita, Medico, Paciente, RolUsuario, Usuario
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
    # Búsqueda libre con LIKE/ILIKE sobre tres columnas (cédula, nombre,
    # apellidos). Cédula usa LIKE (case-sensitive — son dígitos), las otras
    # ILIKE (mayúsculas/minúsculas no importan para el usuario).
    # Orden por apellidos: convención del HTQPJB (registros físicos).
    # limit máximo 200 evita que el front pida la base entera de un golpe.
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
        # E-007 = código de error de la tesis para "cédula duplicada".
        # El frontend reconoce este mensaje y muestra un toast específico
        # ("Ya existe un paciente con esa cédula").
        raise HTTPException(409, "E-007: La cédula ingresada ya está registrada.")

    registrar_auditoria(
        session,
        usuario=actor,
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
        usuario=actor,
        accion=AccionAuditoria.UPDATE,
        tabla="pacientes",
        id_registro=p.id,
        detalle=f"Update {list(data.keys())}",
        ip_origen=request.client.host if request.client else None,
    )
    session.commit()
    session.refresh(p)
    return p


@router.get("/{paciente_id}/historial-medico")
def historial_medico(
    paciente_id: int,
    medico_id: int | None = Query(default=None),
    session: Session = Depends(get_session),
    _: Usuario = Depends(_any_user),
):
    """Historial de consultas atendidas del paciente, opcionalmente filtrado por médico.

    Ordenado por fecha+hora descendente (más reciente primero).

    Solo entran consultas de citas en estado 'atendida' — pendiente o
    cancelada no tendrían información clínica útil.

    El JOIN triple (Consulta ⋈ Cita ⋈ Medico) construye la fila para la
    pantalla de historial: muestra fecha, médico, diagnóstico y plan en
    una sola tabla sin que el frontend tenga que cruzar datos. Incluye
    el campo legacy `observaciones` por si la consulta es vieja y trae
    info ahí en vez de los campos estructurados (Mejora 3.2).
    """
    if not session.get(Paciente, paciente_id):
        raise HTTPException(404, "Paciente no encontrado.")

    stmt = (
        select(Consulta, Cita, Medico)
        .where(
            Consulta.id_cita == Cita.id,
            Cita.id_medico == Medico.id,
            Cita.id_paciente == paciente_id,
            Cita.estado == EstadoCita.atendida,
        )
    )
    if medico_id is not None:
        stmt = stmt.where(Cita.id_medico == medico_id)
    stmt = stmt.order_by(Cita.fecha.desc(), Cita.hora.desc())

    return [
        {
            "id_consulta": c.id,
            "id_cita": cita.id,
            "fecha_consulta": cita.fecha.isoformat(),
            "hora_consulta": formatear_hora_12(cita.hora),
            "medico": m.nombre,
            "id_medico": m.id,
            "especialidad": m.especialidad,
            "motivo_consulta": c.motivo_consulta,
            "examen_fisico": c.examen_fisico,
            "condicion_principal": c.condicion_principal,
            "condiciones_secundarias": c.condiciones_secundarias,
            "tratamiento": c.tratamiento,
            "observaciones": c.observaciones,
        }
        for c, cita, m in session.exec(stmt).all()
    ]


@router.delete("/{paciente_id}", status_code=204)
def eliminar(
    paciente_id: int,
    request: Request,
    session: Session = Depends(get_session),
    actor: Usuario = Depends(_staff),
):
    # CUIDADO: borrado físico, NO soft delete. Solo se usa para pacientes
    # recién registrados sin citas (corregir typo de cédula). Si el
    # paciente tiene citas, la FK de citas → pacientes truena con
    # IntegrityError 500 (no manejado explícitamente). El frontend
    # debe esconder el botón de eliminar cuando hay citas asociadas.
    p = session.get(Paciente, paciente_id)
    if not p:
        raise HTTPException(404, "Paciente no encontrado.")
    session.delete(p)
    registrar_auditoria(
        session,
        usuario=actor,
        accion=AccionAuditoria.DELETE,
        tabla="pacientes",
        id_registro=paciente_id,
        detalle=f"Eliminado cedula={p.cedula}",
        ip_origen=request.client.host if request.client else None,
    )
    session.commit()
