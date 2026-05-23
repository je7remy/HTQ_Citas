"""Punto de entrada FastAPI del SGCM.

CONTEXTO: este módulo NO arranca el servidor — eso lo hace uvicorn vía
el docker-entrypoint. Lo que hace es construir la instancia `app` que
uvicorn levanta. La variable global `app` al final del archivo es la
que importa uvicorn ("app.main:app").

Estructura:
  - create_app(): factory que arma la app con middleware y rutas.
  - /health: endpoint público (sin auth) para que docker-compose y
    el balanceador chequeen liveness.
  - /api/v1/_debug/rutas: introspección de rutas (útil tras rebuilds).
  - exception_handler global: traduce cualquier excepción no manejada
    a 500 con JSON, en vez de el HTML feo de FastAPI por default.
"""
import logging

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.api.v1.router import api_router
from app.core.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s :: %(message)s")
logger = logging.getLogger("sgcm")


def create_app() -> FastAPI:
    # docs_url y openapi_url van bajo /api/v1/ para que Nginx pueda
    # restringir /api/v1/docs detrás de auth si hace falta en producción.
    # Hoy quedan abiertos para facilitar el QA durante la tesis.
    app = FastAPI(
        title=settings.APP_NAME,
        version="1.0.0",
        description="Sistema Web de Gestión de Citas Médicas — HTQPJB",
        docs_url=f"{settings.API_V1_PREFIX}/docs",
        openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
    )

    # CORS permisivo dentro de la lista blanca de BACKEND_CORS_ORIGINS.
    # En la práctica frontend y API viven detrás del mismo Nginx, así
    # que CORS rara vez se dispara — sirve solo para entornos de QA
    # donde el front se sirve desde otro host.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.BACKEND_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router, prefix=settings.API_V1_PREFIX)

    @app.get("/health", tags=["meta"])
    def health():
        # Liveness probe. Devuelve 200 incluso si Postgres está caído —
        # solo confirma que el proceso FastAPI responde. Suficiente para
        # docker healthcheck; un readiness probe verdadero requeriría
        # también hacer SELECT 1 a la BD.
        return {"status": "ok", "service": settings.APP_NAME}

    @app.get(f"{settings.API_V1_PREFIX}/_debug/rutas", tags=["meta"])
    def debug_rutas():
        """Lista las rutas registradas — útil para verificar que el contenedor
        tiene la versión más reciente del código tras un rebuild.

        No requiere autenticación porque solo expone metadatos del router
        (no datos de la BD). Si se quiere endurecer, añadir Depends(_admin).
        """
        rutas = []
        for r in app.routes:
            path = getattr(r, "path", None)
            metodos = sorted(list(getattr(r, "methods", []) or []))
            if path:
                rutas.append({"path": path, "methods": metodos})
        return {"total": len(rutas), "rutas": rutas}

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        # Cualquier excepción NO HTTPException llega acá. La loggeamos con
        # stack trace completo (logger.exception) y devolvemos un mensaje
        # genérico al cliente — NO leak de detalles internos (queries,
        # paths del filesystem, etc.) que podrían ser explotables.
        logger.exception("Unhandled error en %s", request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Error interno del servidor."},
        )

    return app


# Instancia global que uvicorn importa al arrancar: `uvicorn app.main:app`.
# No mover ni renombrar — el docker-entrypoint.sh apunta a este símbolo.
app = create_app()
