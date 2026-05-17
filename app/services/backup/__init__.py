"""Sistema de respaldos del SGCM (CU-16).

Expone el patrón Strategy a través de :class:`BackupStrategy` y el orquestador
:func:`crear_respaldo` que invoca pg_dump, calcula el hash SHA-256, persiste
los metadatos en la tabla `respaldos` y delega la entrega del archivo a la
estrategia adecuada (local, externo, nube).
"""
from app.services.backup.base import BackupResultado, BackupStrategy
from app.services.backup.manager import (
    crear_respaldo,
    obtener_estrategia,
    generar_dump_sql,
    calcular_hash_sha256,
)

__all__ = [
    "BackupStrategy",
    "BackupResultado",
    "crear_respaldo",
    "obtener_estrategia",
    "generar_dump_sql",
    "calcular_hash_sha256",
]
