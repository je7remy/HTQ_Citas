"""Pruebas del módulo de seeders (app.db.seed)."""
from datetime import date, time

from sqlmodel import select

from app.db import seed as seed_mod
from app.models import (
    Cita,
    Consulta,
    EstadoCita,
    Horario,
    Medico,
    Paciente,
    RolUsuario,
    SexoPaciente,
    Usuario,
)


# ----------------------------------------------------------------------
# 1) No duplica datos al ejecutarse repetidamente.
# ----------------------------------------------------------------------
def test_seed_no_duplica_datos(session):
    seed_mod.seed_all(session)
    snapshot = {
        "usuarios": len(session.exec(select(Usuario)).all()),
        "medicos": len(session.exec(select(Medico)).all()),
        "horarios": len(session.exec(select(Horario)).all()),
        "pacientes": len(session.exec(select(Paciente)).all()),
        "citas": len(session.exec(select(Cita)).all()),
        "consultas": len(session.exec(select(Consulta)).all()),
    }

    # Segunda corrida — los conteos NO deben crecer.
    seed_mod.seed_all(session)
    assert {
        "usuarios": len(session.exec(select(Usuario)).all()),
        "medicos": len(session.exec(select(Medico)).all()),
        "horarios": len(session.exec(select(Horario)).all()),
        "pacientes": len(session.exec(select(Paciente)).all()),
        "citas": len(session.exec(select(Cita)).all()),
        "consultas": len(session.exec(select(Consulta)).all()),
    } == snapshot


# ----------------------------------------------------------------------
# 2) Cédulas dominicanas válidas (algoritmo de verificación real).
# ----------------------------------------------------------------------
def test_seed_genera_cedulas_validas(session):
    seed_mod.seed_pacientes(session)
    pacientes = session.exec(select(Paciente)).all()
    assert len(pacientes) >= 30, "se esperan al menos 30 pacientes"

    for p in pacientes:
        assert seed_mod.cedula_dominicana_es_valida(p.cedula), (
            f"cédula inválida en seed: {p.cedula}"
        )

    # Sanity check del propio algoritmo con casos negativos.
    assert not seed_mod.cedula_dominicana_es_valida("12345678901")  # dígito incorrecto
    assert not seed_mod.cedula_dominicana_es_valida("ABCDEFGHIJK")
    assert not seed_mod.cedula_dominicana_es_valida("123")


# ----------------------------------------------------------------------
# 3) Las relaciones entre entidades son coherentes.
# ----------------------------------------------------------------------
def test_seed_crea_relaciones_correctas(session):
    seed_mod.seed_all(session)

    # 3a) Cada médico con id_usuario apunta a un Usuario con rol=medico.
    medicos = session.exec(select(Medico).where(Medico.id_usuario.is_not(None))).all()
    assert medicos, "el seed debe crear médicos vinculados a usuarios"
    for m in medicos:
        u = session.get(Usuario, m.id_usuario)
        assert u is not None
        assert u.rol == RolUsuario.medico

    # 3b) Cada horario referencia un médico existente.
    for h in session.exec(select(Horario)).all():
        assert session.get(Medico, h.id_medico) is not None

    # 3c) Cada cita tiene paciente, médico y secretaria válidos.
    citas = session.exec(select(Cita)).all()
    assert citas, "el seed debe crear citas"
    for c in citas:
        assert session.get(Paciente, c.id_paciente) is not None
        assert session.get(Medico, c.id_medico) is not None
        sec = session.get(Usuario, c.id_secretaria)
        assert sec is not None and sec.rol in (RolUsuario.secretaria, RolUsuario.admin)

    # 3d) Cada consulta corresponde a una cita atendida (uno-a-uno).
    consultas = session.exec(select(Consulta)).all()
    citas_atendidas_ids = {
        c.id for c in citas if c.estado == EstadoCita.atendida
    }
    assert {c.id_cita for c in consultas} <= citas_atendidas_ids
    # Y debe haber al menos una consulta (hay 30% atendidas).
    assert consultas, "el seed debe generar consultas para las citas atendidas"

    # 3e) Hay al menos 4 secretarias, 1 admin y 1 usuario médico inactivo.
    usuarios = session.exec(select(Usuario)).all()
    roles = [u.rol for u in usuarios]
    assert roles.count(RolUsuario.admin) >= 1
    assert roles.count(RolUsuario.secretaria) >= 4
    assert roles.count(RolUsuario.medico) >= 5
    assert any(u.rol == RolUsuario.medico and not u.activo for u in usuarios), (
        "el seed debe incluir un médico inactivo"
    )


# ----------------------------------------------------------------------
# 4) Respeta los CHECK constraints del esquema.
# ----------------------------------------------------------------------
def test_seed_respeta_check_constraints(session):
    seed_mod.seed_all(session)

    valores_sexo = {s.value for s in SexoPaciente}
    for p in session.exec(select(Paciente)).all():
        assert p.sexo in valores_sexo

    for h in session.exec(select(Horario)).all():
        assert 1 <= h.dia_semana <= 7
        assert h.hora_inicio < h.hora_fin

    estados_validos = {e.value for e in EstadoCita}
    for c in session.exec(select(Cita)).all():
        # El modelo deserializa a enum; comparar contra valores válidos.
        estado_val = c.estado.value if hasattr(c.estado, "value") else c.estado
        assert estado_val in estados_validos


# ----------------------------------------------------------------------
# 5) Idempotente — se puede ejecutar dos veces sin error y sin duplicar.
# ----------------------------------------------------------------------
def test_seed_idempotente_se_puede_ejecutar_dos_veces(session):
    # Primera corrida: tablas vacías.
    resumen1 = seed_mod.seed_all(session)
    assert resumen1["usuarios"] >= 10
    assert resumen1["pacientes"] >= 30

    # Segunda corrida: no debe lanzar IntegrityError y los conteos no crecen.
    resumen2 = seed_mod.seed_all(session)
    assert resumen2 == resumen1


# ----------------------------------------------------------------------
# Extra: el seed parcial (--solo usuarios) tampoco duplica.
# ----------------------------------------------------------------------
def test_seed_usuarios_idempotente_solo(session):
    seed_mod.seed_usuarios(session)
    n1 = len(session.exec(select(Usuario)).all())
    seed_mod.seed_usuarios(session)
    n2 = len(session.exec(select(Usuario)).all())
    assert n1 == n2 >= 10


# ----------------------------------------------------------------------
# Extra: el admin se puede usar para autenticarse con la contraseña documentada.
# ----------------------------------------------------------------------
def test_seed_admin_password_es_valida(session):
    from app.core.security import verify_password

    seed_mod.seed_usuarios(session)
    admin = session.exec(
        select(Usuario).where(Usuario.email == seed_mod.ADMIN_EMAIL)
    ).first()
    assert admin is not None
    assert verify_password(seed_mod.ADMIN_PASSWORD, admin.password_hash)
