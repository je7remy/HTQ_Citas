"""Siembra inicial: admin, médico de prueba, secretaria y horarios.

Uso:
    docker compose exec api python -m scripts.seed
"""
from datetime import time

from sqlmodel import Session, select

from app.core.security import hash_password
from app.db.session import engine, init_db
from app.models import Horario, Medico, RolUsuario, Usuario


def seed() -> None:
    init_db()
    with Session(engine) as s:
        if s.exec(select(Usuario).where(Usuario.email == "admin@htqpjb.gob.do")).first():
            print("Seed ya aplicado.")
            return

        admin = Usuario(
            nombre="Administrador SGCM",
            email="admin@htqpjb.gob.do",
            password_hash=hash_password("Admin*2026"),
            rol=RolUsuario.admin,
        )
        secretaria = Usuario(
            nombre="Secretaria HTQPJB",
            email="secretaria@htqpjb.gob.do",
            password_hash=hash_password("Secret*2026"),
            rol=RolUsuario.secretaria,
        )
        medico_user = Usuario(
            nombre="Dr. Juan Pérez",
            email="jperez@htqpjb.gob.do",
            password_hash=hash_password("Medico*2026"),
            rol=RolUsuario.medico,
        )
        s.add_all([admin, secretaria, medico_user])
        s.flush()

        medico = Medico(
            id_usuario=medico_user.id,
            nombre="Juan Pérez",
            especialidad="Ortopedia y Traumatología",
            telefono="809-555-0100",
        )
        s.add(medico)
        s.flush()

        # Lunes a viernes 8:00–12:00
        for dia in range(1, 6):
            s.add(Horario(
                id_medico=medico.id,
                dia_semana=dia,
                hora_inicio=time(8, 0),
                hora_fin=time(12, 0),
            ))

        s.commit()
        print("Seed completado.")
        print("  admin:      admin@htqpjb.gob.do      / Admin*2026")
        print("  secretaria: secretaria@htqpjb.gob.do / Secret*2026")
        print("  medico:     jperez@htqpjb.gob.do     / Medico*2026")


if __name__ == "__main__":
    seed()
