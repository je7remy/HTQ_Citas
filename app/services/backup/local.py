"""Respaldo local: copia el .sql a un directorio dentro del propio servidor."""
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
        self.destino_dir.mkdir(parents=True, exist_ok=True)
        destino = self.destino_dir / archivo_sql.name
        shutil.copy2(archivo_sql, destino)

        hash_destino = _hash_archivo(destino)
        tamano = destino.stat().st_size

        self._ultima_ruta = destino
        return BackupResultado(
            ruta_destino=str(destino),
            hash_destino=hash_destino,
            tamano_bytes=tamano,
        )

    def verificar_integridad(self, hash_origen: str) -> bool:
        if self._ultima_ruta is None or not self._ultima_ruta.exists():
            return False
        return _hash_archivo(self._ultima_ruta) == hash_origen


def _hash_archivo(ruta: Path, chunk: int = 65536) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as f:
        for bloque in iter(lambda: f.read(chunk), b""):
            h.update(bloque)
    return h.hexdigest()
