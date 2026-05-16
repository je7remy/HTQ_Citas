#!/bin/sh
# Punto de entrada del contenedor sgcm_api.
#
# Responsabilidades:
#   1. Garantizar que las tablas existan (init_db).
#   2. Si SGCM_SEED=true, ejecutar el seeder para tener datos desde el primer
#      arranque (datos demo del HTQPJB). Útil en dev y demos; debe quedar en
#      false en producción.
#   3. Lanzar el proceso pasado por CMD (uvicorn).
set -e

echo "[entrypoint] Asegurando esquema de la base de datos…"
python -c "from app.db.session import init_db; init_db()"

SEED_FLAG="${SGCM_SEED:-false}"
if [ "$SEED_FLAG" = "true" ] || [ "$SEED_FLAG" = "TRUE" ] || [ "$SEED_FLAG" = "1" ]; then
    echo "[entrypoint] SGCM_SEED=$SEED_FLAG → ejecutando seed_db…"
    python -m app.scripts.seed_db
else
    echo "[entrypoint] SGCM_SEED=$SEED_FLAG → omitiendo seed (default seguro para producción)."
fi

echo "[entrypoint] Arrancando proceso principal: $*"
exec "$@"
