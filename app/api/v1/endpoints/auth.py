"""Endpoints de autenticación."""
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
    """Login OAuth2 — `username` = email."""
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
    return current
