"""Orquestador del flujo de respaldo (CU-16).

Responsabilidades:
1. Generar el .sql temporal con ``pg_dump``.
2. Calcular el hash SHA-256 del origen.
3. Persistir un registro inicial en la tabla ``respaldos`` (estado ``en_progreso``).
4. Delegar la entrega del archivo a la estrategia indicada.
5. Verificar integridad y cerrar el registro (``completado`` o ``fallido``).

DECISIÓN DE DISEÑO: el flujo se atrapa en un try/except ancho a propósito.
La filosofía es "el respaldo NUNCA debe tumbar el endpoint" — si falla,
deja una fila con estado='fallido' y mensaje_error claro, y el admin
ve el problema en la pantalla de Respaldos. Subir la excepción haría
que el endpoint devuelva 500 y la fila quedaría inconsistente.
"""
from __future__ import annotations

import hashlib
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Optional

from sqlmodel import Session

from app.core.config import settings
from app.core.datetime_utils import ahora_local
from app.models import (
    EstadoRespaldo,
    ProveedorNube,
    Respaldo,
    TipoRespaldo,
    Usuario,
)
from app.services.backup.base import BackupResultado, BackupStrategy
from app.services.backup.externo import RespaldoExterno
from app.services.backup.local import RespaldoLocal
from app.services.backup.nube import RespaldoAzure, RespaldoGCS, RespaldoS3

logger = logging.getLogger("sgcm.backup")


# ─────────────────────────── Helpers públicos ───────────────────────────
def calcular_hash_sha256(ruta: Path, chunk: int = 65536) -> str:
    """SHA-256 hex del archivo. Streaming para no cargar todo a memoria."""
    h = hashlib.sha256()
    with ruta.open("rb") as f:
        for bloque in iter(lambda: f.read(chunk), b""):
            h.update(bloque)
    return h.hexdigest()


def generar_dump_sql(destino: Optional[Path] = None) -> Path:
    """Ejecuta ``pg_dump`` y devuelve la ruta del archivo .sql producido.

    Lanza :class:`subprocess.CalledProcessError` si pg_dump falla. El llamador
    (``crear_respaldo``) captura la excepción y deja el registro en ``fallido``.

    OJO: PGPASSWORD viaja por variable de entorno del subproceso — NO
    aparece en la lista de argumentos (que sí queda visible en `ps aux`).
    Es la forma estándar y segura de pasarle la password a pg_dump.

    --no-owner y --no-privileges: dejan el .sql portable entre instancias
    distintas de PostgreSQL. Si se restaura el dump en otro servidor con
    usuario distinto, no falla por GRANT/OWNER inexistentes.
    """
    if destino is None:
        ts = ahora_local().strftime("%Y%m%d_%H%M%S")
        destino = Path(tempfile.gettempdir()) / f"sgcm_backup_{ts}.sql"

    cmd = [
        "pg_dump",
        "-h", settings.POSTGRES_HOST,
        "-p", str(settings.POSTGRES_PORT),
        "-U", settings.POSTGRES_USER,
        "-d", settings.POSTGRES_DB,
        "-f", str(destino),
        "--no-owner",
        "--no-privileges",
    ]
    env = {"PGPASSWORD": settings.POSTGRES_PASSWORD}
    subprocess.run(cmd, check=True, capture_output=True, text=True, env=env)
    return destino


def obtener_estrategia(
    tipo: TipoRespaldo | str,
    proveedor_nube: Optional[ProveedorNube | str] = None,
) -> BackupStrategy:
    """Devuelve la instancia de estrategia correspondiente al ``tipo``.

    Para ``tipo == 'nube'`` requiere ``proveedor_nube``.
    """
    tipo_v = tipo.value if hasattr(tipo, "value") else str(tipo)
    if tipo_v == "local":
        return RespaldoLocal(settings.SGCM_BACKUP_LOCAL_DIR)
    if tipo_v == "externo":
        return RespaldoExterno(settings.SGCM_BACKUP_EXTERNAL_DIR)
    if tipo_v == "nube":
        if proveedor_nube is None:
            raise ValueError("Debe especificar proveedor_nube cuando tipo='nube'.")
        prov = proveedor_nube.value if hasattr(proveedor_nube, "value") else str(proveedor_nube)
        if prov == "s3":
            return RespaldoS3(
                bucket=settings.SGCM_BACKUP_S3_BUCKET,
                region=settings.SGCM_BACKUP_S3_REGION,
            )
        if prov == "gcs":
            return RespaldoGCS(bucket=settings.SGCM_BACKUP_GCS_BUCKET)
        if prov == "azure":
            return RespaldoAzure(container=settings.SGCM_BACKUP_AZURE_CONTAINER)
        raise ValueError(f"Proveedor de nube desconocido: {prov}")
    raise ValueError(f"Tipo de respaldo desconocido: {tipo_v}")


# ─────────────────────────── Orquestador ───────────────────────────
def crear_respaldo(
    session: Session,
    *,
    usuario: Usuario,
    tipo: TipoRespaldo | str,
    proveedor_nube: Optional[ProveedorNube | str] = None,
    dump_fn: Optional[Callable[[], Path]] = None,
    strategy: Optional[BackupStrategy] = None,
) -> Respaldo:
    """Ejecuta el flujo completo y persiste el resultado.

    ``dump_fn`` y ``strategy`` se inyectan en tests para evitar depender de
    pg_dump o del sistema de archivos real. En producción se usan los defaults.

    Siempre persiste un registro en la tabla ``respaldos``, incluso cuando el
    flujo falla — así el administrador ve el intento en el histórico con el
    ``mensaje_error`` correspondiente.

    Manejo de excepciones (intencional):
      - NotImplementedError → estrategia stub (S3/GCS/Azure). Se loggea
        como warning porque es un caso esperado mientras no se activen
        los SDK de nube; no spammea Sentry/logs como un error real.
      - Exception → cualquier otro fallo (pg_dump, FS lleno, hash no
        coincide). Se loggea con stack trace completo para diagnóstico.

    El registro final SIEMPRE tiene hash_sha256 no nulo: si falló antes
    de calcularlo, se rellena con 64 ceros como placeholder — la columna
    es NOT NULL en BD y un INSERT sin valor abortaría la transacción.
    """
    # Normalizamos a strings — el modelo Respaldo guarda VARCHAR, no enums.
    tipo_str: str = tipo.value if hasattr(tipo, "value") else str(tipo)
    prov_str: Optional[str]
    if proveedor_nube is None:
        prov_str = None
    elif hasattr(proveedor_nube, "value"):
        prov_str = proveedor_nube.value
    else:
        prov_str = str(proveedor_nube)

    if strategy is None:
        strategy = obtener_estrategia(tipo_str, prov_str)

    inicio = ahora_local()
    archivo: Optional[Path] = None
    hash_origen: str = ""
    ruta_destino: str = ""
    tamano: int = 0
    error_msg: Optional[str] = None
    estado_str: str = EstadoRespaldo.en_progreso.value

    try:
        fn = dump_fn if dump_fn is not None else generar_dump_sql
        archivo = fn()
        hash_origen = calcular_hash_sha256(archivo)
        resultado: BackupResultado = strategy.ejecutar(archivo)
        ruta_destino = resultado.ruta_destino
        tamano = resultado.tamano_bytes

        integridad_ok = strategy.verificar_integridad(hash_origen)
        if not integridad_ok:
            raise RuntimeError(
                "Verificación de integridad fallida: el hash del archivo en "
                "destino no coincide con el del origen."
            )
        estado_str = EstadoRespaldo.completado.value
    except NotImplementedError as exc:
        estado_str = EstadoRespaldo.fallido.value
        error_msg = str(exc)
        logger.warning("Respaldo no implementado: %s", exc)
    except Exception as exc:
        estado_str = EstadoRespaldo.fallido.value
        error_msg = _formatear_error(exc)
        logger.exception("Fallo en crear_respaldo")

    fin = ahora_local()
    duracion = int(max(0, (fin - inicio).total_seconds()))

    registro = Respaldo(
        id_usuario=usuario.id,
        nombre_usuario=usuario.nombre,
        tipo=tipo_str,
        proveedor_nube=prov_str,
        ruta_origen=str(archivo) if archivo else "(no generado)",
        ruta_destino=ruta_destino or "(no entregado)",
        tamano_bytes=tamano,
        hash_sha256=hash_origen or ("0" * 64),
        estado=estado_str,
        mensaje_error=error_msg,
        fecha_inicio=inicio,
        fecha_fin=fin,
        duracion_segundos=duracion,
    )
    session.add(registro)
    session.commit()
    session.refresh(registro)
    return registro


def _formatear_error(exc: Exception) -> str:
    if isinstance(exc, subprocess.CalledProcessError):
        stderr = (exc.stderr or "").strip()
        if stderr:
            return f"pg_dump falló (exit {exc.returncode}): {stderr[:500]}"
        return f"pg_dump falló con exit {exc.returncode}."
    return f"{type(exc).__name__}: {exc}"
