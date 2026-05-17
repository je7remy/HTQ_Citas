"""Router agregado de la API v1."""
from fastapi import APIRouter

from app.api.v1.endpoints import (
    auditoria,
    auth,
    citas,
    consultas,
    medicos,
    pacientes,
    reportes,
    reportes_admin,
    respaldos,
    usuarios,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(usuarios.router)
api_router.include_router(pacientes.router)
api_router.include_router(medicos.router)
api_router.include_router(citas.router)
api_router.include_router(consultas.router)
api_router.include_router(reportes.router)
api_router.include_router(reportes_admin.router)
api_router.include_router(auditoria.router)
api_router.include_router(respaldos.router)
