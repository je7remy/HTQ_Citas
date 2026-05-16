"""CLI para poblar la base de datos del SGCM.

Uso:
    python -m app.scripts.seed_db                 # ejecuta seed_all
    python -m app.scripts.seed_db --reset         # borra todo y repuebla
    python -m app.scripts.seed_db --solo usuarios # ejecuta solo una sección

Secciones válidas para --solo:
    usuarios, medicos, horarios, pacientes, citas, consultas

El comando es idempotente: ejecutarlo dos veces no duplica datos.
"""
from __future__ import annotations

import argparse
import logging
import sys

from sqlmodel import Session

from app.db import seed as seed_mod
from app.db.session import engine, init_db

_SECCIONES = ("usuarios", "medicos", "horarios", "pacientes", "citas", "consultas")


def _configurar_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="[seed_db] %(levelname)s %(message)s",
    )


def _ejecutar_seccion(session: Session, seccion: str) -> None:
    if seccion == "usuarios":
        seed_mod.seed_usuarios(session)
    elif seccion == "medicos":
        seed_mod.seed_medicos(session)
    elif seccion == "horarios":
        seed_mod.seed_horarios(session)
    elif seccion == "pacientes":
        seed_mod.seed_pacientes(session)
    elif seccion == "citas":
        seed_mod.seed_citas(session)
    elif seccion == "consultas":
        seed_mod.seed_consultas(session)
    else:  # pragma: no cover — argparse ya valida choices
        raise ValueError(f"Sección desconocida: {seccion}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="seed_db",
        description="Pobla la base de datos del SGCM con datos iniciales del HTQPJB.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Borra todos los datos antes de poblar (peligroso, solo para dev).",
    )
    parser.add_argument(
        "--solo",
        choices=_SECCIONES,
        help="Ejecuta únicamente una sección del seed.",
    )
    args = parser.parse_args(argv)

    _configurar_logging()

    # Garantiza que las tablas existan antes de poblar.
    init_db()

    with Session(engine) as session:
        if args.reset:
            print("[seed_db] --reset: vaciando todas las tablas…")
            seed_mod.reset_datos(session)

        if args.solo:
            print(f"[seed_db] Ejecutando solo la sección: {args.solo}")
            _ejecutar_seccion(session, args.solo)
        else:
            resumen = seed_mod.seed_all(session)
            print("[seed_db] Resumen:")
            for k, v in resumen.items():
                print(f"  - {k}: {v}")

    print("[seed_db] Listo. Credenciales en el README (sección 'Credenciales').")
    return 0


if __name__ == "__main__":
    sys.exit(main())
