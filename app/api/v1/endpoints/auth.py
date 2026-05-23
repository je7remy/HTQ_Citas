"""Endpoints de autenticación.

CONTEXTO: única puerta de entrada al sistema. POST /auth/login emite
el JWT que TODOS los demás endpoints exigen vía Depends(get_current_user).

GET /auth/me es el ping de "sigo autenticado" que el frontend usa al
arrancar la app: si responde 200, monta la UI; si responde 401, manda
a /login.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import Session, select

from app.api.deps import get_current_user
from app.core.security import create_access_token, verify_password
from app.db.session import get_session
from app.models import AccionAuditoria, Usuario
from app.schemas import TokenResponse, UsuarioRead
from app.services.audit import registrar_auditoria

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(
    request: Request,
    form: OAuth2PasswordRequestForm = Depends(),
    session: Session = Depends(get_session),
):
    """Login OAuth2 — `username` = email.

    OJO: mismo mensaje "Email o contraseña incorrectos" tanto si el email
    no existe como si la password está mal. Es deliberado para no filtrar
    a un atacante si un email determinado es válido en el sistema.

    Usuario inactivo → 403, NO 401. Distinción importante: el usuario
    SÍ existe y la contraseña ESTÁ bien, pero el admin lo desactivó. El
    frontend muestra un mensaje específico ("Tu cuenta fue desactivada,
    contacta al administrador") en vez del genérico de credenciales.

    El LOGIN se audita SIEMPRE que sea exitoso (Ley 172-13). Los fallos
    no se auditan a propósito: una bitácora con miles de intentos
    fallidos sería ruido y dificultaría leer la auditoría real.
    """
    user = session.exec(select(Usuario).where(Usuario.email == form.username)).first()
    if not user or not verify_password(form.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email o contraseña incorrectos.",
        )
    if not user.activo:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Usuario inactivo.")

    token = create_access_token(subject=user.id, role=user.rol.value)

    registrar_auditoria(
        session,
        usuario=user,
        accion=AccionAuditoria.LOGIN,
        tabla="usuarios",
        id_registro=user.id,
        detalle=f"Login exitoso ({user.email})",
        ip_origen=request.client.host if request.client else None,
    )
    session.commit()

    return TokenResponse(
        access_token=token,
        rol=user.rol,
        nombre=user.nombre,
        user_id=user.id,
    )


@router.get("/me", response_model=UsuarioRead)
def me(current: Usuario = Depends(get_current_user)):
    # Heartbeat de sesión. El frontend lo invoca al cargar cualquier
    # pantalla protegida — si responde 200 con el usuario, todo bien;
    # si responde 401, redirige a login. NO se audita: ruido innecesario.
    return current
