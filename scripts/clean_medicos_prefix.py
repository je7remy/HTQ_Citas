"""Elimina prefijos tipo "Dr." / "Dra." de la columna nombre de la tabla medicos.

Ejecutar UNA VEZ con: docker exec sgcm_api python scripts/clean_medicos_prefix.py
El script es idempotente: una segunda ejecución no modifica nada.
"""
import re

from sqlmodel import Session, select

from app.db.session import engine, init_db
from app.models import Medico

_PREFIJO = re.compile(
    r"^(dra?\.?\s+|doctor[a]?\s+)",
    re.IGNORECASE,
)


def strip_prefix(nombre: str) -> str:
    return _PREFIJO.sub("", nombre).strip()


def main() -> None:
    init_db()
    limpiados = 0
    sin_cambios = 0
    with Session(engine) as s:
        medicos = s.exec(select(Medico)).all()
        for m in medicos:
            limpio = strip_prefix(m.nombre)
            if limpio != m.nombre:
                m.nombre = limpio
                s.add(m)
                limpiados += 1
            else:
                sin_cambios += 1
        s.commit()
    print(f"{limpiados} médico(s) limpiado(s), {sin_cambios} sin cambios.")


if __name__ == "__main__":
    main()
