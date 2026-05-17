"""Respaldo externo: copia el .sql a una ruta montada (USB / UNC / NFS).

Reutiliza la lógica de copia segura del respaldo local pero apunta a un
directorio diferente, y deja un mensaje claro si el punto de montaje no
está disponible (caso típico cuando el disco USB no está conectado).
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from app.services.backup.base import BackupResultado, BackupStrategy
from app.services.backup.local import RespaldoLocal


class RespaldoExterno(BackupStrategy):
    nombre = "externo"
    proveedor_nube: Optional[str] = None

    def __init__(self, destino_dir: str | Path):
        self.destino_dir = Path(destino_dir)
        self._impl = RespaldoLocal(self.destino_dir)

    def ejecutar(self, archivo_sql: Path) -> BackupResultado:
        padre = self.destino_dir.parent
        if not padre.exists():
            raise FileNotFoundError(
                f"La ruta padre del destino externo no existe: {padre}. "
                "Verifique que el disco USB o el recurso de red esté montado."
            )
        return self._impl.ejecutar(archivo_sql)

    def verificar_integridad(self, hash_origen: str) -> bool:
        return self._impl.verificar_integridad(hash_origen)
