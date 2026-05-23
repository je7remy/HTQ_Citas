"""Dependencias FastAPI: usuario actual + RBAC.

CONTEXTO: este módulo es el corazón del control de acceso del SGCM.
Toda ruta que necesite saber QUIÉN está llamando o LIMITAR por rol
debe usar `Depends(get_current_user)` o `Depends(require_roles(...))`.

Modelo de roles:
  - admin: ve y modifica todo.
  - secretaria: gestiona pacientes, citas, agenda; sin acceso a admin.
  - medico: ve su agenda, registra consultas; lectura limitada.

Decisiones que no son obvias del código:
  - El JWT trae el rol pero NO lo usamos para autorizar — recargamos
    el Usuario de BD en cada request para que un cambio de rol o un
    `activo=False` surtan efecto al instante (sin esperar exp del JWT).
  - Usuario inactivo se trata como NO autenticado: devolvemos 401 (no
    403). Razón: el frontend tiene catch genérico de 401 que redirige
    a /login; un 403 dejaría al usuario varado.
"""
from typing import Iterable

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlmodel import Session, select

from app.core.config import settings
from app.core.security import decode_token
from app.db.session import get_session
from app.models import RolUsuario, Usuario

# tokenUrl apunta al endpoint de login DEL MISMO PROYECTO. Lo usa
# Swagger UI para mostrar el botón "Authorize" — no es para producción.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_PREFIX}/auth/login")

# Excepción reutilizable. Definir una sola vez evita repetir el header
# WWW-Authenticate en cada raise (OAuth2 lo requiere para 401).
_CRED_EXC = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Credenciales inválidas o expiradas.",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    token: str = Depends(oauth2_scheme),
    session: Session = Depends(get_session),
) -> Usuario:
    """Resuelve el usuario autenticado a partir del bearer token.

    Falla con 401 si:
      - El token no es decodable, expiró o tiene firma inválida.
      - El `sub` del payload no es un entero válido.
      - El usuario fue borrado de BD entre emisión del token y ahora.
      - El usuario está inactivo (admin lo dio de baja con soft delete).

    Devuelve el modelo Usuario completo para que los endpoints accedan
    a current.id, current.rol, current.nombre sin volver a la BD.
    """
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
    """Factory de dependencias para restringir endpoints por rol.

    Patrón de uso (en endpoints/*.py):
        _admin = require_roles(RolUsuario.admin)
        _staff = require_roles(RolUsuario.secretaria, RolUsuario.admin)
        ...
        def endpoint(actor: Usuario = Depends(_admin)): ...

    El `actor` devuelto es el Usuario ya autenticado; el cierre interno
    encadena get_current_user → chequea rol → devuelve usuario o 403.

    OJO: el set `allowed` se calcula UNA SOLA VEZ al definir la dependencia
    (cuando se invoca require_roles), no en cada request. Eso lo hace
    más eficiente y predecible.
    """
    allowed: set[str] = {r.value for r in roles}

    def _checker(current: Usuario = Depends(get_current_user)) -> Usuario:
        if current.rol.value not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Acceso denegado. Roles permitidos: {sorted(allowed)}",
            )
        return current

    return _checker
