"""Dependencias FastAPI: usuario actual + RBAC."""
from typing import Iterable

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlmodel import Session, select

from app.core.config import settings
from app.core.security import decode_token
from app.db.session import get_session
from app.models import RolUsuario, Usuario

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_PREFIX}/auth/login")

_CRED_EXC = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Credenciales inválidas o expiradas.",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    token: str = Depends(oauth2_scheme),
    session: Session = Depends(get_session),
) -> Usuario:
    try:
        payload = decode_token(token)
        user_id = int(payload.get("sub"))
    except (ValueError, TypeError):
        raise _CRED_EXC

    user = session.get(Usuario, user_id)
    if not user or not user.activo:
        raise _CRED_EXC
    return user


def require_roles(*roles: RolUsuario):
    """Factory de dependencias para restringir endpoints por rol."""
    allowed: set[str] = {r.value for r in roles}

    def _checker(current: Usuario = Depends(get_current_user)) -> Usuario:
        if current.rol.value not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Acceso denegado. Roles permitidos: {sorted(allowed)}",
            )
        return current

    return _checker
