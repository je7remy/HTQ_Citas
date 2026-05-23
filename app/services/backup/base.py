"""Patrón Strategy para el sistema de respaldos.

CONTEXTO: el CU-16 del SGCM exige que el admin pueda respaldar la BD
a tres tipos de destino: local (mismo servidor), externo (USB/NFS) y
nube (S3/GCS/Azure). En vez de un if-else gigante, cada destino es
una BackupStrategy concreta y el manager elige cuál instanciar.

Añadir un destino nuevo (ej. SFTP) implica:
  1. Crear app/services/backup/<nombre>.py con una clase que herede
     BackupStrategy.
  2. Registrarla en obtener_estrategia() del manager.
  3. Documentar la configuración en docs/BACKUPS.md.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class BackupResultado:
    """Resultado retornado por una estrategia de respaldo.

    - ``ruta_destino``: ubicación final del .sql (path local, ruta UNC, URI s3://...).
    - ``hash_destino``: SHA-256 calculado sobre el archivo entregado al destino.
      Permite que el orquestador verifique integridad sin volver a leer el origen.
    - ``tamano_bytes``: tamaño en bytes del archivo entregado al destino.
    """

    ruta_destino: str
    hash_destino: str
    tamano_bytes: int
    metadatos: Optional[dict] = None


class BackupStrategy(ABC):
    """Interfaz común de toda estrategia de respaldo."""

    #: Identificador corto que el manager usa para registro en BD ('local', 'externo', 'nube').
    nombre: str = ""
    #: Proveedor en caso de estrategias de nube (s3/gcs/azure). None para local/externo.
    proveedor_nube: Optional[str] = None

    @abstractmethod
    def ejecutar(self, archivo_sql: Path) -> BackupResultado:
        """Recibe el .sql generado y lo deposita en su destino final.

        Debe devolver :class:`BackupResultado` con la ruta efectiva y el hash
        del archivo ya colocado en destino. Levanta excepción si falla.
        """

    @abstractmethod
    def verificar_integridad(self, hash_origen: str) -> bool:
        """Verifica que el archivo destino tenga el mismo SHA-256 que el origen.

        La estrategia debe re-leer el archivo en destino (o consultar el hash
        publicado por el proveedor de nube) y compararlo con ``hash_origen``.
        """
