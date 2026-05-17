"""Tests del sistema de respaldos (CU-16).

Inyectamos un ``dump_fn`` falso que genera un .sql en un tempdir para no
depender de pg_dump en el entorno de pruebas. La lógica de hash, integridad,
copia a destino y persistencia es la real.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from sqlmodel import select

from app.models import Respaldo
from app.services.backup import calcular_hash_sha256, crear_respaldo
from app.services.backup.local import RespaldoLocal


# ───────────────────────── Helpers ─────────────────────────
def _hacer_dump_falso(tmp_path: Path, contenido: bytes = b"-- SGCM dump\nSELECT 1;\n"):
    """Devuelve una función ``dump_fn`` apta para inyectar en crear_respaldo."""
    def _fn() -> Path:
        archivo = tmp_path / "sgcm_backup_FAKE.sql"
        archivo.write_bytes(contenido)
        return archivo
    return _fn


def _fake_pg_dump_fallido():
    import subprocess
    def _fn() -> Path:
        raise subprocess.CalledProcessError(
            returncode=1, cmd=["pg_dump"], output="", stderr="connection refused"
        )
    return _fn


# ───────────────────────── 1. Local ─────────────────────────
def test_backup_local_genera_archivo(session, auth_as, tmp_path, monkeypatch):
    auth_as("admin")
    dest = tmp_path / "respaldos"
    monkeypatch.setattr("app.core.config.settings.SGCM_BACKUP_LOCAL_DIR", str(dest))

    from app.models import RolUsuario, Usuario
    admin = session.exec(select(Usuario).where(Usuario.rol == RolUsuario.admin)).first()

    r = crear_respaldo(
        session,
        usuario=admin,
        tipo="local",
        dump_fn=_hacer_dump_falso(tmp_path),
    )
    assert r.estado == "completado"
    assert r.tipo == "local"
    archivo = Path(r.ruta_destino)
    assert archivo.exists()
    assert archivo.parent == dest


def test_backup_local_calcula_hash_correctamente(session, auth_as, tmp_path, monkeypatch):
    """El hash registrado debe coincidir con SHA-256 del contenido del .sql."""
    auth_as("admin")
    monkeypatch.setattr("app.core.config.settings.SGCM_BACKUP_LOCAL_DIR", str(tmp_path / "out"))
    from app.models import RolUsuario, Usuario
    admin = session.exec(select(Usuario).where(Usuario.rol == RolUsuario.admin)).first()
    contenido = b"-- contenido determinista\nINSERT INTO t VALUES (1);\n"
    esperado = hashlib.sha256(contenido).hexdigest()

    r = crear_respaldo(
        session, usuario=admin, tipo="local",
        dump_fn=_hacer_dump_falso(tmp_path, contenido=contenido),
    )
    assert r.estado == "completado"
    assert r.hash_sha256 == esperado
    # Y el archivo en destino tiene el mismo hash
    assert calcular_hash_sha256(Path(r.ruta_destino)) == esperado


def test_backup_local_se_registra_en_tabla_respaldos(session, auth_as, tmp_path, monkeypatch):
    auth_as("admin")
    monkeypatch.setattr("app.core.config.settings.SGCM_BACKUP_LOCAL_DIR", str(tmp_path / "out"))
    from app.models import RolUsuario, Usuario
    admin = session.exec(select(Usuario).where(Usuario.rol == RolUsuario.admin)).first()

    crear_respaldo(session, usuario=admin, tipo="local", dump_fn=_hacer_dump_falso(tmp_path))
    crear_respaldo(session, usuario=admin, tipo="local", dump_fn=_hacer_dump_falso(tmp_path))

    rows = session.exec(select(Respaldo).where(Respaldo.tipo == "local")).all()
    assert len(rows) == 2
    for r in rows:
        assert r.id_usuario == admin.id
        assert r.nombre_usuario == admin.nombre
        assert r.tamano_bytes > 0
        assert r.duracion_segundos is not None and r.duracion_segundos >= 0


# ───────────────────────── 2. Externo ─────────────────────────
def test_backup_externo_copia_a_ruta_configurada(session, auth_as, tmp_path, monkeypatch):
    auth_as("admin")
    # El "punto de montaje" externo es un subdirectorio dentro de tmp_path.
    externo = tmp_path / "mnt" / "backup_externo"
    monkeypatch.setattr("app.core.config.settings.SGCM_BACKUP_EXTERNAL_DIR", str(externo))
    from app.models import RolUsuario, Usuario
    admin = session.exec(select(Usuario).where(Usuario.rol == RolUsuario.admin)).first()

    # La ruta padre (tmp_path/"mnt") sí existe, simulando un disco montado.
    externo.parent.mkdir(parents=True, exist_ok=True)

    r = crear_respaldo(session, usuario=admin, tipo="externo", dump_fn=_hacer_dump_falso(tmp_path))
    assert r.estado == "completado"
    assert r.tipo == "externo"
    assert Path(r.ruta_destino).exists()
    assert Path(r.ruta_destino).is_relative_to(externo)


def test_backup_externo_falla_si_punto_montaje_no_existe(session, auth_as, tmp_path, monkeypatch):
    """Si el padre del directorio externo no existe (USB desconectado), debe fallar limpio."""
    auth_as("admin")
    inexistente = tmp_path / "no_existe" / "backup_externo"
    monkeypatch.setattr("app.core.config.settings.SGCM_BACKUP_EXTERNAL_DIR", str(inexistente))
    from app.models import RolUsuario, Usuario
    admin = session.exec(select(Usuario).where(Usuario.rol == RolUsuario.admin)).first()

    r = crear_respaldo(session, usuario=admin, tipo="externo", dump_fn=_hacer_dump_falso(tmp_path))
    assert r.estado == "fallido"
    assert "no existe" in (r.mensaje_error or "").lower()


# ───────────────────────── 3. Nube (stubs) ─────────────────────────
def test_backup_nube_lanza_NotImplementedError_con_mensaje_claro(session, auth_as, tmp_path):
    auth_as("admin")
    from app.models import RolUsuario, Usuario
    admin = session.exec(select(Usuario).where(Usuario.rol == RolUsuario.admin)).first()

    r = crear_respaldo(
        session,
        usuario=admin,
        tipo="nube",
        proveedor_nube="s3",
        dump_fn=_hacer_dump_falso(tmp_path),
    )
    assert r.estado == "fallido"
    assert "S3" in (r.mensaje_error or "") or "s3" in (r.mensaje_error or "")
    assert r.proveedor_nube == "s3"


# ───────────────────────── 4. Fallo pg_dump ─────────────────────────
def test_backup_registra_estado_fallido_si_pg_dump_falla(session, auth_as, tmp_path, monkeypatch):
    auth_as("admin")
    monkeypatch.setattr("app.core.config.settings.SGCM_BACKUP_LOCAL_DIR", str(tmp_path / "out"))
    from app.models import RolUsuario, Usuario
    admin = session.exec(select(Usuario).where(Usuario.rol == RolUsuario.admin)).first()

    r = crear_respaldo(
        session, usuario=admin, tipo="local", dump_fn=_fake_pg_dump_fallido()
    )
    assert r.estado == "fallido"
    assert "pg_dump" in (r.mensaje_error or "")
    assert "connection refused" in (r.mensaje_error or "")


# ───────────────────────── 5. Verificación de integridad ─────────────────────────
def test_backup_verifica_integridad_con_hash(session, auth_as, tmp_path, monkeypatch):
    """Si la estrategia reporta hash distinto al de origen, el respaldo falla."""
    auth_as("admin")
    from app.models import RolUsuario, Usuario
    admin = session.exec(select(Usuario).where(Usuario.rol == RolUsuario.admin)).first()

    class EstrategiaConHashCorrupto(RespaldoLocal):
        def verificar_integridad(self, hash_origen: str) -> bool:
            return False  # forzar mismatch

    estrategia = EstrategiaConHashCorrupto(tmp_path / "out")
    r = crear_respaldo(
        session, usuario=admin, tipo="local",
        dump_fn=_hacer_dump_falso(tmp_path), strategy=estrategia,
    )
    assert r.estado == "fallido"
    assert "integridad" in (r.mensaje_error or "").lower()


# ───────────────────────── 6. RBAC ─────────────────────────
def test_backup_solo_admin_403_otros_roles(client, auth_as):
    auth_as("secretaria")
    res = client.post("/api/v1/respaldos", json={"tipo": "local"})
    assert res.status_code == 403

    auth_as("medico")
    res = client.post("/api/v1/respaldos", json={"tipo": "local"})
    assert res.status_code == 403

    # Listado también restringido
    auth_as("secretaria")
    assert client.get("/api/v1/respaldos").status_code == 403


# ───────────────────────── 7. Descarga ─────────────────────────
def test_descargar_backup_local_devuelve_archivo(client, session, auth_as, tmp_path, monkeypatch):
    auth_as("admin")
    monkeypatch.setattr("app.core.config.settings.SGCM_BACKUP_LOCAL_DIR", str(tmp_path / "out"))
    from app.models import RolUsuario, Usuario
    admin = session.exec(select(Usuario).where(Usuario.rol == RolUsuario.admin)).first()

    r = crear_respaldo(
        session, usuario=admin, tipo="local",
        dump_fn=_hacer_dump_falso(tmp_path, contenido=b"-- bytes\n"),
    )
    assert r.estado == "completado"

    res = client.get(f"/api/v1/respaldos/{r.id}/descargar")
    assert res.status_code == 200
    assert res.content.startswith(b"-- bytes")
    assert "filename=" in res.headers.get("content-disposition", "").lower()


def test_descargar_backup_externo_devuelve_error_con_ruta(client, session, auth_as, tmp_path, monkeypatch):
    auth_as("admin")
    externo = tmp_path / "mnt" / "backup_externo"
    externo.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("app.core.config.settings.SGCM_BACKUP_EXTERNAL_DIR", str(externo))
    from app.models import RolUsuario, Usuario
    admin = session.exec(select(Usuario).where(Usuario.rol == RolUsuario.admin)).first()

    r = crear_respaldo(
        session, usuario=admin, tipo="externo",
        dump_fn=_hacer_dump_falso(tmp_path),
    )
    assert r.estado == "completado"

    res = client.get(f"/api/v1/respaldos/{r.id}/descargar")
    assert res.status_code == 400
    detail = res.json()["detail"]
    assert "local" in detail.lower()
    assert r.ruta_destino in detail  # incluye la ruta donde está


# ───────────────────────── 8. Endpoint listar/detalle/eliminar ─────────────────────────
def test_endpoints_listar_filtrar_y_eliminar(client, session, auth_as, tmp_path, monkeypatch):
    auth_as("admin")
    monkeypatch.setattr("app.core.config.settings.SGCM_BACKUP_LOCAL_DIR", str(tmp_path / "out"))
    from app.models import RolUsuario, Usuario
    admin = session.exec(select(Usuario).where(Usuario.rol == RolUsuario.admin)).first()

    # Generar 3 respaldos: 2 locales completados + 1 nube fallido
    for _ in range(2):
        crear_respaldo(session, usuario=admin, tipo="local", dump_fn=_hacer_dump_falso(tmp_path))
    fallido = crear_respaldo(
        session, usuario=admin, tipo="nube", proveedor_nube="gcs",
        dump_fn=_hacer_dump_falso(tmp_path),
    )
    assert fallido.estado == "fallido"

    # GET listado total
    res = client.get("/api/v1/respaldos")
    assert res.status_code == 200
    items = res.json()
    assert len(items) == 3

    # GET filtrado por tipo=local
    res = client.get("/api/v1/respaldos?tipo=local")
    assert res.status_code == 200
    assert all(i["tipo"] == "local" for i in res.json())
    assert len(res.json()) == 2

    # GET filtrado por estado=fallido
    res = client.get("/api/v1/respaldos?estado=fallido")
    assert res.status_code == 200
    body = res.json()
    assert len(body) == 1
    assert body[0]["estado"] == "fallido"

    # GET detalle
    rid = body[0]["id"]
    res = client.get(f"/api/v1/respaldos/{rid}")
    assert res.status_code == 200
    assert res.json()["id"] == rid

    # DELETE elimina solo el registro: el archivo físico se conserva si existe
    # (en este caso el fallido no tiene archivo entregado).
    res = client.delete(f"/api/v1/respaldos/{rid}")
    assert res.status_code == 204
    assert client.get(f"/api/v1/respaldos/{rid}").status_code == 404


# ───────────────────────── 9. Creación vía endpoint ─────────────────────────
def test_post_respaldos_admin_crea_local(client, session, auth_as, tmp_path, monkeypatch):
    """Test end-to-end: el POST debe invocar el flujo y devolver 201 con el registro.

    Inyectamos un dump_fn falso reemplazando ``generar_dump_sql`` en el manager.
    """
    auth_as("admin")
    monkeypatch.setattr("app.core.config.settings.SGCM_BACKUP_LOCAL_DIR", str(tmp_path / "out"))

    # Reemplazar el generador real (que llamaría a pg_dump) por uno falso.
    from app.services.backup import manager as bk_manager
    contenido = b"-- e2e dump\nSELECT now();\n"
    archivo_falso = tmp_path / "sgcm_backup_e2e.sql"

    def _dump_fn() -> Path:
        archivo_falso.write_bytes(contenido)
        return archivo_falso

    monkeypatch.setattr(bk_manager, "generar_dump_sql", _dump_fn)

    res = client.post("/api/v1/respaldos", json={"tipo": "local"})
    assert res.status_code == 201
    body = res.json()
    assert body["tipo"] == "local"
    assert body["estado"] == "completado"
    assert body["hash_sha256"] == hashlib.sha256(contenido).hexdigest()


def test_post_respaldos_tipo_nube_sin_proveedor_falla_422(client, auth_as):
    auth_as("admin")
    res = client.post("/api/v1/respaldos", json={"tipo": "nube"})
    assert res.status_code == 422
    assert "proveedor_nube" in res.json()["detail"]
