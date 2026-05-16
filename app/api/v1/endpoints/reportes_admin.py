"""Reportes administrativos: estadísticas de usuarios y médicos.

Endpoints restringidos a administrador. Exponen versiones JSON (consumidas
por el frontend para tarjetas/tablas) y versiones PDF generadas con
WeasyPrint para descarga e impresión.
"""
from collections import Counter
from datetime import timedelta
from io import BytesIO
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from jinja2 import Template
from sqlalchemy import func
from sqlmodel import Session, select
from weasyprint import HTML

from app.api.deps import require_roles
from app.core.datetime_utils import (
    ahora_local,
    formatear_fecha_emision,
    formatear_fecha_hora,
)
from app.db.session import get_session
from app.models import (
    AccionAuditoria,
    Cita,
    Consulta,
    EstadoCita,
    Horario,
    Medico,
    RolUsuario,
    Usuario,
)
from app.schemas import (
    MedicoDetalleStats,
    MedicosDetalleResponse,
    UsuariosResumen,
)
from app.services.audit import registrar_auditoria

router = APIRouter(prefix="/reportes", tags=["reportes"])

_admin = require_roles(RolUsuario.admin)


# ───────────────── Plantillas WeasyPrint ─────────────────
_BASE_CSS = """
  @page { size: A4; margin: 1.8cm; }
  body { font-family: 'Helvetica', sans-serif; color: #1f2937; font-size: 11pt; }
  h1 { color: #1e40af; margin: 0; font-size: 19pt; }
  h2 { color: #1e40af; margin: 22px 0 8px 0; font-size: 13pt;
       border-bottom: 2px solid #1e40af; padding-bottom: 4px; }
  h3 { color: #1f2937; margin: 14px 0 6px 0; font-size: 11.5pt; }
  .institucion { color: #4b5563; font-size: 10pt; margin-top: 2px; }
  .emision { color: #9ca3af; font-size: 9pt; margin-top: 4px; }
  table { width: 100%; border-collapse: collapse; margin-top: 6px; }
  th { background: #1e40af; color: white; text-align: left; padding: 7px 8px; font-size: 9.5pt; }
  td { padding: 6px 8px; border-bottom: 1px solid #e5e7eb; font-size: 9.5pt; }
  tr:nth-child(even) td { background: #f9fafb; }
  .num { text-align: right; font-variant-numeric: tabular-nums; }
  .badge { padding: 2px 8px; border-radius: 10px; font-size: 8.5pt; font-weight: bold; }
  .activo   { background: #dcfce7; color: #166534; }
  .inactivo { background: #f3f4f6; color: #4b5563; }
  .rol-admin      { background: #ede9fe; color: #5b21b6; }
  .rol-secretaria { background: #ccfbf1; color: #115e59; }
  .rol-medico     { background: #dbeafe; color: #1e3a8a; }
  .resumen-card { background: #f9fafb; padding: 12px 16px; border-radius: 6px;
                  border: 1px solid #e5e7eb; margin-top: 18px; }
  .resumen-card h2 { margin-top: 0; border: none; }
  .resumen-table td { background: transparent !important; border-bottom: none;
                      padding: 3px 14px 3px 0; }
  .resumen-table td.label { color: #4b5563; }
  .resumen-table td.value { text-align: right; font-variant-numeric: tabular-nums;
                            font-weight: 600; }
  .resumen-table tr.total td { font-weight: bold; border-top: 1px solid #d1d5db;
                               padding-top: 6px; }
  .extras li { margin: 4px 0; }
  footer { position: fixed; bottom: 0; left: 0; right: 0; text-align: center;
           color: #9ca3af; font-size: 8pt; }
"""

_USUARIOS_TEMPLATE = """
<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8" />
<title>Reporte de Usuarios — SGCM</title>
<style>{{ base_css }}</style>
</head>
<body>
  <h1>Reporte de Usuarios del Sistema</h1>
  <p class="institucion">
    Hospital Regional Traumatológico y Quirúrgico Prof. Juan Bosch — SGCM<br/>
    La Vega, República Dominicana
  </p>
  <p class="emision">Reporte generado el {{ fecha_emision }}</p>

  <h2>Resumen por rol</h2>
  <table>
    <thead>
      <tr>
        <th>Rol</th>
        <th class="num">Total</th>
        <th class="num">Activos</th>
        <th class="num">Inactivos</th>
      </tr>
    </thead>
    <tbody>
      {% for rol, stats in resumen_rol %}
      <tr>
        <td><span class="badge rol-{{ rol }}">{{ rol|capitalize }}</span></td>
        <td class="num">{{ stats.total }}</td>
        <td class="num">{{ stats.activos }}</td>
        <td class="num">{{ stats.inactivos }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>

  {% for rol, usuarios in usuarios_por_rol %}
    {% if usuarios %}
    <h2>Detalle de {{ rol|capitalize }}</h2>
    <table>
      <thead>
        <tr>
          <th>#</th><th>Nombre</th><th>Email</th>
          <th>Estado</th><th>Fecha de creación</th>
        </tr>
      </thead>
      <tbody>
        {% for u in usuarios %}
        <tr>
          <td>{{ loop.index }}</td>
          <td>{{ u.nombre }}</td>
          <td>{{ u.email }}</td>
          <td>
            {% if u.activo %}<span class="badge activo">Activo</span>
            {% else %}<span class="badge inactivo">Inactivo</span>{% endif %}
          </td>
          <td>{{ u.fecha_creacion_fmt }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% endif %}
  {% endfor %}

  <h2>Estadísticas adicionales</h2>
  <h3>Médicos por especialidad (top 5)</h3>
  {% if top_especialidades %}
  <table>
    <thead><tr><th>#</th><th>Especialidad</th><th class="num">Médicos</th></tr></thead>
    <tbody>
      {% for esp, n in top_especialidades %}
      <tr><td>{{ loop.index }}</td><td>{{ esp }}</td><td class="num">{{ n }}</td></tr>
      {% endfor %}
    </tbody>
  </table>
  {% else %}
  <p class="emision">Sin médicos registrados.</p>
  {% endif %}

  <h3>Secretaria con más citas creadas (últimos 30 días)</h3>
  {% if top_secretaria %}
  <p>{{ top_secretaria.nombre }} — {{ top_secretaria.total }} cita(s) creada(s).</p>
  {% else %}
  <p class="emision">Sin citas registradas en los últimos 30 días.</p>
  {% endif %}

  <h3>Médico con más consultas registradas (últimos 30 días)</h3>
  {% if top_medico_consultas %}
  <p>{{ top_medico_consultas.nombre }} — {{ top_medico_consultas.total }} consulta(s).</p>
  {% else %}
  <p class="emision">Sin consultas registradas en los últimos 30 días.</p>
  {% endif %}

  <div class="resumen-card">
    <h2>Resumen final</h2>
    <table class="resumen-table">
      <tr><td class="label">Administradores</td><td class="value">{{ totales.admin }}</td></tr>
      <tr><td class="label">Secretarias</td><td class="value">{{ totales.secretaria }}</td></tr>
      <tr><td class="label">Médicos</td><td class="value">{{ totales.medico }}</td></tr>
      <tr class="total"><td class="label">Total general</td>
          <td class="value">{{ totales.total }}</td></tr>
    </table>
  </div>

  <footer>SGCM — Generado automáticamente · HTQPJB · La Vega, R.D.</footer>
</body>
</html>
"""

_MEDICOS_TEMPLATE = """
<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8" />
<title>Reporte de Médicos — SGCM</title>
<style>{{ base_css }}</style>
</head>
<body>
  <h1>Reporte de Médicos Activos</h1>
  <p class="institucion">
    Hospital Regional Traumatológico y Quirúrgico Prof. Juan Bosch — SGCM<br/>
    La Vega, República Dominicana
  </p>
  <p class="emision">Reporte generado el {{ fecha_emision }}</p>

  <h2>Listado de médicos activos</h2>
  {% if medicos %}
  <table>
    <thead>
      <tr>
        <th>#</th>
        <th>Médico</th>
        <th>Especialidad principal</th>
        <th>Especialidades secundarias</th>
        <th class="num">Citas</th>
        <th class="num">Consultas</th>
        <th class="num">% Atendidas</th>
        <th class="num">% Canceladas</th>
        <th class="num">Días disp.</th>
      </tr>
    </thead>
    <tbody>
      {% for m in medicos %}
      <tr>
        <td>{{ loop.index }}</td>
        <td><strong>Dr. {{ m.nombre }}</strong></td>
        <td>{{ m.especialidad }}</td>
        <td>{{ m.especialidades_secundarias_str or '—' }}</td>
        <td class="num">{{ m.total_citas }}</td>
        <td class="num">{{ m.total_consultas }}</td>
        <td class="num">{{ '%.1f'|format(m.tasa_atendidas) }}%</td>
        <td class="num">{{ '%.1f'|format(m.tasa_canceladas) }}%</td>
        <td class="num">{{ m.dias_disponibilidad }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% else %}
  <p class="emision">No hay médicos activos registrados.</p>
  {% endif %}

  <div class="resumen-card">
    <h2>Resumen final</h2>
    <table class="resumen-table">
      <tr><td class="label">Total de médicos activos</td>
          <td class="value">{{ resumen.total_medicos }}</td></tr>
      <tr><td class="label">Total de citas asignadas</td>
          <td class="value">{{ resumen.total_citas }}</td></tr>
      <tr><td class="label">Total de consultas registradas</td>
          <td class="value">{{ resumen.total_consultas }}</td></tr>
      <tr class="total"><td class="label">Promedio de citas por médico</td>
          <td class="value">{{ '%.1f'|format(resumen.promedio_citas) }}</td></tr>
    </table>
  </div>

  <footer>SGCM — Generado automáticamente · HTQPJB · La Vega, R.D.</footer>
</body>
</html>
"""


# ───────────────── Helpers ─────────────────
_GENERO_ROL = {
    RolUsuario.admin: ("activos", "inactivos"),
    RolUsuario.medico: ("activos", "inactivos"),
    RolUsuario.secretaria: ("activas", "inactivas"),
}


def _calcular_resumen_usuarios(session: Session) -> tuple[dict, dict]:
    """Retorna (por_rol_dict, totales_dict).

    por_rol_dict respeta el género gramatical (secretaria → activas/inactivas).
    totales_dict expone conteos enteros por rol y total general.
    """
    usuarios = session.exec(select(Usuario)).all()
    por_rol: dict[str, dict[str, int]] = {}
    for rol in RolUsuario:
        en_rol = [u for u in usuarios if u.rol == rol]
        activos = sum(1 for u in en_rol if u.activo)
        key_act, key_inact = _GENERO_ROL[rol]
        por_rol[rol.value] = {
            "total": len(en_rol),
            key_act: activos,
            key_inact: len(en_rol) - activos,
        }
    totales = {
        "admin": por_rol["admin"]["total"],
        "secretaria": por_rol["secretaria"]["total"],
        "medico": por_rol["medico"]["total"],
        "total": len(usuarios),
    }
    return por_rol, totales


def _top_especialidades(session: Session, limite: int = 5) -> list[tuple[str, int]]:
    medicos = session.exec(select(Medico).where(Medico.activo == True)).all()  # noqa: E712
    counts: Counter[str] = Counter(m.especialidad for m in medicos)
    return counts.most_common(limite)


def _top_secretaria_ultimo_mes(session: Session) -> Optional[dict]:
    desde = ahora_local() - timedelta(days=30)
    stmt = (
        select(Cita.id_secretaria, func.count(Cita.id).label("n"))
        .where(Cita.fecha_registro >= desde)
        .group_by(Cita.id_secretaria)
        .order_by(func.count(Cita.id).desc())
        .limit(1)
    )
    row = session.exec(stmt).first()
    if not row:
        return None
    user = session.get(Usuario, row[0])
    return {"nombre": user.nombre if user else "—", "total": int(row[1])}


def _top_medico_consultas_ultimo_mes(session: Session) -> Optional[dict]:
    desde = ahora_local() - timedelta(days=30)
    stmt = (
        select(Cita.id_medico, func.count(Consulta.id).label("n"))
        .where(Consulta.id_cita == Cita.id, Consulta.fecha_registro >= desde)
        .group_by(Cita.id_medico)
        .order_by(func.count(Consulta.id).desc())
        .limit(1)
    )
    row = session.exec(stmt).first()
    if not row:
        return None
    medico = session.get(Medico, row[0])
    return {"nombre": medico.nombre if medico else "—", "total": int(row[1])}


def _detalle_medicos(session: Session) -> list[MedicoDetalleStats]:
    medicos = session.exec(
        select(Medico).where(Medico.activo == True).order_by(Medico.nombre)  # noqa: E712
    ).all()
    resultado: list[MedicoDetalleStats] = []
    for m in medicos:
        citas = session.exec(select(Cita).where(Cita.id_medico == m.id)).all()
        atendidas = sum(1 for c in citas if c.estado == EstadoCita.atendida)
        canceladas = sum(1 for c in citas if c.estado == EstadoCita.cancelada)
        pendientes = sum(1 for c in citas if c.estado == EstadoCita.pendiente)
        total_citas = len(citas)

        total_consultas = session.exec(
            select(func.count(Consulta.id)).where(
                Consulta.id_cita == Cita.id, Cita.id_medico == m.id
            )
        ).one()
        total_consultas = int(total_consultas or 0)

        dias_disp = session.exec(
            select(func.count(Horario.id)).where(
                Horario.id_medico == m.id, Horario.activo == True  # noqa: E712
            )
        ).one()
        dias_disp = int(dias_disp or 0)

        tasa_atendidas = (atendidas / total_citas * 100) if total_citas else 0.0
        tasa_canceladas = (canceladas / total_citas * 100) if total_citas else 0.0

        secundarias = [
            s for s in (m.especialidad_secundaria_1, m.especialidad_secundaria_2) if s
        ]
        resultado.append(
            MedicoDetalleStats(
                id=m.id,
                nombre=m.nombre,
                especialidad=m.especialidad,
                especialidades_secundarias=secundarias,
                total_citas=total_citas,
                total_consultas=total_consultas,
                citas_atendidas=atendidas,
                citas_canceladas=canceladas,
                citas_pendientes=pendientes,
                tasa_atendidas=round(tasa_atendidas, 2),
                tasa_canceladas=round(tasa_canceladas, 2),
                dias_disponibilidad=dias_disp,
            )
        )
    return resultado


def _registrar_auditoria_reporte(
    session: Session,
    *,
    actor: Usuario,
    request: Request,
    tipo: str,
) -> None:
    registrar_auditoria(
        session,
        usuario=actor,
        accion=AccionAuditoria.CREATE,
        tabla="reportes",
        id_registro=None,
        detalle=f"Generación de reporte: {tipo}",
        ip_origen=request.client.host if request.client else None,
    )
    session.commit()


# ───────────────── Endpoints ─────────────────
@router.get("/usuarios/resumen", response_model=UsuariosResumen)
def resumen_usuarios(
    session: Session = Depends(get_session),
    _: Usuario = Depends(_admin),
):
    por_rol, totales = _calcular_resumen_usuarios(session)
    return UsuariosResumen(
        total_usuarios=totales["total"],
        por_rol=por_rol,
        fecha_generacion=ahora_local(),
    )


@router.get("/usuarios/pdf")
def pdf_usuarios(
    request: Request,
    session: Session = Depends(get_session),
    actor: Usuario = Depends(_admin),
):
    por_rol, totales = _calcular_resumen_usuarios(session)

    usuarios = session.exec(select(Usuario).order_by(Usuario.nombre)).all()
    grouped: dict[str, list] = {r.value: [] for r in RolUsuario}
    for u in usuarios:
        grouped[u.rol.value].append(
            {
                "nombre": u.nombre,
                "email": u.email,
                "activo": u.activo,
                "fecha_creacion_fmt": formatear_fecha_hora(u.fecha_creacion),
            }
        )

    resumen_rol = [
        (rol, por_rol[rol]) for rol in ("admin", "secretaria", "medico")
    ]
    usuarios_por_rol = [
        (rol, grouped[rol]) for rol in ("admin", "secretaria", "medico")
    ]

    top_esp = _top_especialidades(session, limite=5)
    top_sec = _top_secretaria_ultimo_mes(session)
    top_med = _top_medico_consultas_ultimo_mes(session)

    html_str = Template(_USUARIOS_TEMPLATE).render(
        base_css=_BASE_CSS,
        fecha_emision=formatear_fecha_emision(),
        resumen_rol=resumen_rol,
        usuarios_por_rol=usuarios_por_rol,
        totales=totales,
        top_especialidades=top_esp,
        top_secretaria=top_sec,
        top_medico_consultas=top_med,
    )
    pdf_bytes = HTML(string=html_str).write_pdf()

    _registrar_auditoria_reporte(
        session, actor=actor, request=request, tipo="usuarios"
    )

    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'inline; filename="reporte_usuarios.pdf"'
        },
    )


@router.get("/medicos/detalle", response_model=MedicosDetalleResponse)
def detalle_medicos(
    session: Session = Depends(get_session),
    _: Usuario = Depends(_admin),
):
    medicos = _detalle_medicos(session)
    return MedicosDetalleResponse(
        total_medicos=len(medicos),
        medicos=medicos,
        fecha_generacion=ahora_local(),
    )


@router.get("/medicos/pdf")
def pdf_medicos(
    request: Request,
    session: Session = Depends(get_session),
    actor: Usuario = Depends(_admin),
):
    medicos = _detalle_medicos(session)

    medicos_ctx = [
        {
            **m.model_dump(),
            "especialidades_secundarias_str": ", ".join(m.especialidades_secundarias),
        }
        for m in medicos
    ]

    total_citas = sum(m.total_citas for m in medicos)
    total_consultas = sum(m.total_consultas for m in medicos)
    resumen = {
        "total_medicos": len(medicos),
        "total_citas": total_citas,
        "total_consultas": total_consultas,
        "promedio_citas": (total_citas / len(medicos)) if medicos else 0.0,
    }

    html_str = Template(_MEDICOS_TEMPLATE).render(
        base_css=_BASE_CSS,
        fecha_emision=formatear_fecha_emision(),
        medicos=medicos_ctx,
        resumen=resumen,
    )
    pdf_bytes = HTML(string=html_str).write_pdf()

    _registrar_auditoria_reporte(
        session, actor=actor, request=request, tipo="medicos"
    )

    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'inline; filename="reporte_medicos.pdf"'
        },
    )
