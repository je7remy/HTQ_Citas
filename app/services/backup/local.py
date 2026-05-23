"""Respaldo local: copia el .sql a un directorio dentro del propio servidor.

OJO: "local" significa "mismo host del contenedor api". En docker-compose
ese directorio se monta como volumen sgcm_backups, así que los respaldos
sobreviven a rebuilds del contenedor pero NO a una pérdida del host.
Para protección real ante desastre se usa también el respaldo externo
(USB/NFS) y/o el de nube.
"""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Optional

from app.services.backup.base import BackupResultado, BackupStrategy


class RespaldoLocal(BackupStrategy):
    """Persiste el archivo en ``destino_dir`` (configurado por env)."""

    nombre = "local"
    proveedor_nube: Optional[str] = None

    def __init__(self, destino_dir: str | Path):
        self.destino_dir = Path(destino_dir)
        self._ultima_ruta: Optional[Path] = None

    def ejecutar(self, archivo_sql: Path) -> BackupResultado:
        # `mkdir(exist_ok=True)`: la primera vez que se respalda en un
        # entorno nuevo el directorio puede no existir. Mejor crearlo
        # silenciosamente que fallar con "No such file or directory".
        # shutil.copy2 preserva metadata (mtime, permisos) — útil para
        # ordenar copias por fecha en el filesystem.
        self.destino_dir.mkdir(parents=True, exist_ok=True)
        destino = self.destino_dir / archivo_sql.name
        shutil.copy2(archivo_sql, destino)

        hash_destino = _hash_archivo(destino)
        tamano = destino.stat().st_size

        # Guardamos la última ruta para que verificar_integridad pueda
        # releer el archivo sin que el manager tenga que pasársela.
        self._ultima_ruta = destino
        return BackupResultado(
            ruta_destino=str(destino),
            hash_destino=hash_destino,
            tamano_bytes=tamano,
        )

    def verificar_integridad(self, hash_origen: str) -> bool:
        # Releemos el archivo del destino y recalculamos el SHA-256.
        # Si el filesystem se corrompió o alguien tocó el archivo entre
        # ejecutar() y verificar_integridad(), el hash no cuadra y el
        # manager marca el respaldo como fallido.
        if self._ultima_ruta is None or not self._ultima_ruta.exists():
            return False
        return _hash_archivo(self._ultima_ruta) == hash_origen


def _hash_archivo(ruta: Path, chunk: int = 65536) -> str:
    # Lectura por bloques de 64 KB: respaldos de BD del SGCM rondan
    # decenas de MB, leerlo todo a memoria es innecesario y haría más
    # difícil escalar si la BD crece.
    h = hashlib.sha256()
    with ruta.open("rb") as f:
        for bloque in iter(lambda: f.read(chunk), b""):
            h.update(bloque)
    return h.hexdigest()
