"""Generación de reportes en PDF con WeasyPrint."""
from datetime import date as date_type
from io import BytesIO

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select
from weasyprint import HTML

from app.api.deps import require_roles
from app.core.datetime_utils import formatear_fecha_emision
from app.db.session import get_session
from app.models import Cita, Medico, Paciente, RolUsuario, Usuario

router = APIRouter(prefix="/reportes", tags=["reportes"])

_staff = require_roles(RolUsuario.secretaria, RolUsuario.admin, RolUsuario.medico)

_TEMPLATE = """
<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8" />
<title>Reporte de Citas — SGCM</title>
<style>
  @page { size: A4; margin: 1.8cm; }
  body { font-family: 'Helvetica', sans-serif; color: #1f2937; font-size: 11pt; }
  h1 { color: #1e40af; margin-bottom: 0; font-size: 18pt; }
  .sub { color: #6b7280; margin-top: 4px; font-size: 10pt; }
  .emision { color: #9ca3af; font-size: 9pt; margin-top: 2px; }
  table { width: 100%; border-collapse: collapse; margin-top: 18px; }
  th { background: #1e40af; color: white; text-align: left; padding: 8px; font-size: 10pt; }
  td { padding: 7px 8px; border-bottom: 1px solid #e5e7eb; font-size: 10pt; }
  tr:nth-child(even) td { background: #f9fafb; }
  .estado { padding: 2px 8px; border-radius: 10px; font-size: 9pt; font-weight: bold; }
  .pendiente { background: #dbeafe; color: #1e3a8a; }
  .atendida { background: #dcfce7; color: #166534; }
  .cancelada { background: #f3f4f6; color: #4b5563; }
  footer { position: fixed; bottom: 0; left: 0; right: 0; text-align: center;
           color: #9ca3af; font-size: 8pt; }
</style>
</head>
<body>
  <h1>Reporte de Citas Médicas</h1>
  <p class="emision">Reporte generado el {{ fecha_emision }}</p>
  <div class="sub">
    Hospital Regional Traumatológico y Quirúrgico Prof. Juan Bosch — SGCM<br/>
    Rango: {{ desde }} a {{ hasta }}
    {% if medico_nombre %}· Médico: {{ medico_nombre }}{% endif %}<br/>
    Total: {{ filas|length }} cita(s)
  </div>

  <table>
    <thead>
      <tr>
        <th>#</th><th>Fecha</th><th>Hora</th><th>Paciente</th><th>Médico</th><th>Estado</th>
      </tr>
    </thead>
    <tbody>
      {% for r in filas %}
      <tr>
        <td>{{ loop.index }}</td>
        <td>{{ r.fecha }}</td>
        <td>{{ r.hora }}</td>
        <td>{{ r.paciente }}</td>
        <td>{{ r.medico }}</td>
        <td><span class="estado {{ r.estado }}">{{ r.estado }}</span></td>
      </tr>
      {% endfor %}
    </tbody>
  </table>

  <footer>SGCM — Generado automáticamente · HTQPJB · La Vega, R.D.</footer>
</body>
</html>
"""


@router.get("/citas.pdf")
def reporte_citas_pdf(
    desde: date_type = Query(...),
    hasta: date_type = Query(...),
    id_medico: int | None = None,
    session: Session = Depends(get_session),
    _: Usuario = Depends(_staff),
):
    from jinja2 import Template

    stmt = select(Cita, Paciente, Medico).where(
        Cita.id_paciente == Paciente.id,
        Cita.id_medico == Medico.id,
        Cita.fecha >= desde,
        Cita.fecha <= hasta,
    )
    if id_medico:
        stmt = stmt.where(Cita.id_medico == id_medico)
    rows = session.exec(stmt.order_by(Cita.fecha, Cita.hora)).all()

    filas = [
        {
            "id": c.id,
            "fecha": c.fecha.isoformat(),
            "hora": c.hora.strftime("%H:%M"),
            "paciente": f"{p.nombre} {p.apellidos}",
            "medico": m.nombre,
            "estado": c.estado.value,
        }
        for c, p, m in rows
    ]

    medico_nombre = None
    if id_medico:
        m = session.get(Medico, id_medico)
        medico_nombre = m.nombre if m else None

    fecha_emision = formatear_fecha_emision()

    html_str = Template(_TEMPLATE).render(
        desde=desde.isoformat(), hasta=hasta.isoformat(),
        filas=filas, medico_nombre=medico_nombre,
        fecha_emision=fecha_emision,
    )
    pdf_bytes = HTML(string=html_str).write_pdf()

    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="reporte_citas_{desde}_{hasta}.pdf"'},
    )
