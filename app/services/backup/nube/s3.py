"""Stub de respaldo en Amazon S3. Activar instalando boto3."""
from __future__ import annotations

from pathlib import Path

from app.services.backup.base import BackupResultado, BackupStrategy

_MENSAJE = (
    "Respaldo en Amazon S3 aún no implementado. Para activarlo: "
    "(1) instale boto3 en requirements.txt; "
    "(2) configure SGCM_BACKUP_S3_BUCKET y SGCM_BACKUP_S3_REGION; "
    "(3) provea credenciales AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY "
    "(o IAM role). Consulte docs/BACKUPS.md."
)


class RespaldoS3(BackupStrategy):
    nombre = "nube"
    proveedor_nube = "s3"

    def __init__(self, bucket: str, region: str):
        self.bucket = bucket
        self.region = region

    def ejecutar(self, archivo_sql: Path) -> BackupResultado:
        raise NotImplementedError(_MENSAJE)

    def verificar_integridad(self, hash_origen: str) -> bool:
        raise NotImplementedError(_MENSAJE)
