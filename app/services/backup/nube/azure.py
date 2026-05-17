"""Stub de respaldo en Azure Blob Storage. Activar instalando azure-storage-blob."""
from __future__ import annotations

from pathlib import Path

from app.services.backup.base import BackupResultado, BackupStrategy

_MENSAJE = (
    "Respaldo en Azure Blob Storage aún no implementado. Para activarlo: "
    "(1) instale azure-storage-blob en requirements.txt; "
    "(2) configure SGCM_BACKUP_AZURE_CONTAINER; "
    "(3) defina AZURE_STORAGE_CONNECTION_STRING. Consulte docs/BACKUPS.md."
)


class RespaldoAzure(BackupStrategy):
    nombre = "nube"
    proveedor_nube = "azure"

    def __init__(self, container: str):
        self.container = container

    def ejecutar(self, archivo_sql: Path) -> BackupResultado:
        raise NotImplementedError(_MENSAJE)

    def verificar_integridad(self, hash_origen: str) -> bool:
        raise NotImplementedError(_MENSAJE)
