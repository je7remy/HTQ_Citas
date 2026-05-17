"""Estrategias de respaldo en nube (S3, GCS, Azure).

Los tres módulos contienen stubs con interfaz lista. Para activarlos:

1.  Instalar el SDK correspondiente (``boto3``, ``google-cloud-storage``
    o ``azure-storage-blob``) en ``requirements.txt``.
2.  Configurar las credenciales del proveedor (variables de entorno
    estándar del SDK o archivo de credenciales).
3.  Reemplazar el cuerpo del método ``ejecutar`` siguiendo la guía en
    ``docs/BACKUPS.md``.
"""
from app.services.backup.nube.azure import RespaldoAzure
from app.services.backup.nube.gcs import RespaldoGCS
from app.services.backup.nube.s3 import RespaldoS3

__all__ = ["RespaldoS3", "RespaldoGCS", "RespaldoAzure"]
