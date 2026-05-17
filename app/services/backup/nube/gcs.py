"""Stub de respaldo en Google Cloud Storage. Activar instalando google-cloud-storage."""
from __future__ import annotations

from pathlib import Path

from app.services.backup.base import BackupResultado, BackupStrategy

_MENSAJE = (
    "Respaldo en Google Cloud Storage aún no implementado. Para activarlo: "
    "(1) instale google-cloud-storage en requirements.txt; "
    "(2) configure SGCM_BACKUP_GCS_BUCKET; "
    "(3) defina GOOGLE_APPLICATION_CREDENTIALS apuntando al JSON de servicio. "
    "Consulte docs/BACKUPS.md."
)


class RespaldoGCS(BackupStrategy):
    nombre = "nube"
    proveedor_nube = "gcs"

    def __init__(self, bucket: str):
        self.bucket = bucket

    def ejecutar(self, archivo_sql: Path) -> BackupResultado:
        raise NotImplementedError(_MENSAJE)

    def verificar_integridad(self, hash_origen: str) -> bool:
        raise NotImplementedError(_MENSAJE)
