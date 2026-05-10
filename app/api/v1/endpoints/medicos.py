"""CRUD de médicos y gestión de horarios."""
import re

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlmodel import Session, select

from app.api.deps import require_roles
from app.core.especialidades import ESPECIALIDADES_HTQPJB
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
from app.services.disponibilidad_service import proxima_disponibilidad

router = APIRouter(prefix="/medicos", tags=["medicos"])

_admin = require_roles(RolUsuario.admin)
_any = require_roles(RolUsuario.secretaria, RolUsuario.admin, RolUsuario.medico)

_MSG_ESPECIALIDAD_INVALIDA = (
    "Especialidad inválida. Use uno de los valores oficiales del hospital."
)

_PREFIJO_DR = re.compile(r"^(dra?\.?\s+|doctor[a]?\s+)", re.IGNORECASE)


def _strip_doctor_prefix(nombre: str) -> str:
    """Elimina prefijo Dr./Dra./Doctor/Doctora al inicio del nombre."""
    return _PREFIJO_DR.sub("", nombre).strip()


def _validar_especialidad(especialidad: str) -> None:
    if especialidad not in ESPECIALIDADES_HTQPJB:
        raise HTTPException(422, _MSG_ESPECIALIDAD_INVALIDA)


def _validar_especialidades(
    principal: str,
    secundaria_1: str | None,
    secundaria_2: str | None,
) -> None:
    """Valida principal + secundarias contra el catálogo y la unicidad."""
    _validar_especialidad(principal)
    if secundaria_1 is not None:
        _validar_especialidad(secundaria_1)
    if secundaria_2 is not None:
        _validar_especialidad(secundaria_2)
    valores = [v for v in (principal, secundaria_1, secundaria_2) if v is not None]
    if len(valores) != len(set(valores)):
        raise HTTPException(
            422,
            "Las especialidades principal y secundarias deben ser distintas entre sí.",
        )


# ---------- Especialidades ----------
@router.get("/especialidades")
def listar_especialidades(_: Usuario = Depends(_any)):
    return {"especialidades": ESPECIALIDADES_HTQPJB}


# ---------- Médicos ----------
@router.get("", response_model=list[MedicoRead])
def listar(session: Session = Depends(get_session), _: Usuario = Depends(_any)):
    return session.exec(select(Medico).where(Medico.activo == True).order_by(Medico.nombre)).all()  # noqa: E712


@router.get("/{medico_id}/proxima-disponibilidad")
def get_proxima_disponibilidad(
    medico_id: int,
    session: Session = Depends(get_session),
    _: Usuario = Depends(_any),
):
    """Sugerencia de próximo slot libre del médico (None si no hay en 30 días)."""
    return proxima_disponibilidad(session, medico_id)


@router.post("", response_model=MedicoRead, status_code=status.HTTP_201_CREATED)
def crear(
    payload: MedicoCreate,
    request: Request,
    session: Session = Depends(get_session),
    actor: Usuario = Depends(_admin),
):
    _validar_especialidades(
        payload.especialidad,
        payload.especialidad_secundaria_1,
        payload.especialidad_secundaria_2,
    )
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
    data = payload.model_dump()
    data["nombre"] = _strip_doctor_prefix(data["nombre"])
    m = Medico(**data)
    session.add(m)
    session.flush()
    registrar_auditoria(
        session,
        usuario=actor,
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
    _validar_especialidades(
        payload.medico.especialidad,
        payload.medico.especialidad_secundaria_1,
        payload.medico.especialidad_secundaria_2,
    )
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
        nombre=_strip_doctor_prefix(payload.medico.nombre),
        especialidad=payload.medico.especialidad,
        especialidad_secundaria_1=payload.medico.especialidad_secundaria_1,
        especialidad_secundaria_2=payload.medico.especialidad_secundaria_2,
        telefono=payload.medico.telefono,
    )
    session.add(m)
    session.flush()

    registrar_auditoria(
        session,
        usuario=actor,
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
    esp_keys = {"especialidad", "especialidad_secundaria_1", "especialidad_secundaria_2"}
    if data.keys() & esp_keys:
        principal = data.get("especialidad", m.especialidad)
        sec1 = data["especialidad_secundaria_1"] if "especialidad_secundaria_1" in data else m.especialidad_secundaria_1
        sec2 = data["especialidad_secundaria_2"] if "especialidad_secundaria_2" in data else m.especialidad_secundaria_2
        _validar_especialidades(principal, sec1, sec2)
    if "nombre" in data:
        data["nombre"] = _strip_doctor_prefix(data["nombre"])
    for k, v in data.items():
        setattr(m, k, v)
    session.add(m)
    registrar_auditoria(
        session,
        usuario=actor,
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
        usuario=actor,
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
        usuario=actor,
        accion=AccionAuditoria.DELETE,
        tabla="horarios",
        id_registro=horario_id,
        detalle="Soft delete horario",
        ip_origen=request.client.host if request.client else None,
    )
    session.commit()
