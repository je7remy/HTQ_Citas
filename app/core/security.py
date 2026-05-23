"""Hashing de contraseñas y emisión/validación de JWT.

CONTEXTO: este módulo es la única puerta para autenticación. Cualquier
endpoint que verifique credenciales o emita tokens pasa por aquí, así
que si hay que cambiar el algoritmo de hashing (a argon2, p.ej.) o
rotar la JWT secret key, el blast radius es local.

OJO: aquí SÍ usamos datetime.now(timezone.utc) en vez de ahora_local()
a propósito — el campo `exp` del JWT es un timestamp Unix (segundos
desde epoch UTC) por convención de la RFC 7519. Mezclar TZ dominicana
en el JWT no romperá nada (Unix epoch es UTC siempre) pero confunde
a quien lee el código pensando que el SGCM nunca usa UTC.
"""
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

# bcrypt con `deprecated="auto"`: passlib actualiza el hash si la fila
# vieja usa un esquema anticuado al verificar. Hoy todos los hashes son
# bcrypt nuevos, pero el flag deja la puerta abierta para una migración
# futura sin romper logins.
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """Genera el hash bcrypt para guardar en BD.

    bcrypt incluye un salt aleatorio por cada hash, así que la misma
    password produce hashes distintos en cada llamada. Eso es deseado:
    impide ataques de rainbow tables.
    """
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    """Verifica una contraseña en claro contra el hash almacenado.

    passlib hace la comparación en tiempo constante para que un atacante
    no pueda deducir información de cuán parecido es lo que envió a la
    contraseña real basándose en el tiempo de respuesta.
    """
    return pwd_context.verify(plain, hashed)


def create_access_token(subject: str | int, role: str, extra: dict[str, Any] | None = None) -> str:
    """Emite un JWT firmado con HS256.

    Payload mínimo:
      - sub: id de usuario (string).
      - role: rol para chequeo RBAC sin tener que ir a BD en cada request.
      - iat / exp: emitido y expira.

    `extra` permite anidar info adicional (ej. user_id explícito o nombre)
    sin tocar la firma de esta función.

    CUIDADO: el rol viaja en el token. Si en algún momento se permite
    cambiar el rol de un usuario "en caliente", su JWT anterior seguirá
    teniendo el rol viejo hasta que expire. Para revocaciones inmediatas
    habría que añadir una lista negra de tokens (no implementado hoy).
    """
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "role": role,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    """Decodifica y valida un JWT. Lanza ValueError si está mal.

    python-jose verifica firma + expiración automáticamente. Si el token
    expiró o la firma no cuadra, JWTError sube y se traduce a ValueError
    para que el middleware/dependency lo convierta en 401 Unauthorized.
    """
    try:
        return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError as e:
        raise ValueError(f"Token inválido: {e}") from e
