"""Router agregado de la API v1.

CONTEXTO: este archivo es el ÚNICO punto donde se registran sub-routers
de la API. Si añades un endpoint nuevo, primero creas el módulo en
endpoints/ con su `router = APIRouter(prefix=...)` y luego lo enganchas
acá. No registrarlo hace que el endpoint quede invisible aunque exista
el archivo.

OJO: el orden de include_router NO afecta la resolución de rutas
(FastAPI las matchea por path), pero ayuda a leer el archivo en orden
de "importancia funcional" (auth primero, luego entidades, luego
operaciones, luego reportes/auditoría/respaldos).

NOTA: reportes.router y reportes_admin.router comparten el prefijo
/reportes; FastAPI los mergea por path sin colisión porque los paths
internos no se solapan (citas.pdf/agenda/* vs usuarios/*, medicos/*).
"""
from fastapi import APIRouter

from app.api.v1.endpoints import (
    auditoria,
    auth,
    citas,
    consultas,
    especialidades,
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
api_router.include_router(especialidades.router)
api_router.include_router(citas.router)
api_router.include_router(consultas.router)
api_router.include_router(reportes.router)
api_router.include_router(reportes_admin.router)
api_router.include_router(auditoria.router)
api_router.include_router(respaldos.router)
