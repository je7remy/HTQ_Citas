#!/bin/sh
# Punto de entrada del contenedor sgcm_api.
#
# Responsabilidades:
#   1. Garantizar que las tablas existan (init_db).
#   2. Si SGCM_SEED=true, ejecutar el seeder para tener datos desde el primer
#      arranque (datos demo del HTQPJB). Útil en dev y demos; debe quedar en
#      false en producción.
#   3. Lanzar el proceso pasado por CMD (uvicorn).
#
# CONTEXTO: este script se ejecuta cada vez que arranca el contenedor
# (no solo en build). Por eso init_db es idempotente — si las tablas ya
# existen no hace nada, si faltan las crea.
#
# OJO: init.sql del contenedor de PostgreSQL ya creó las tablas en la
# primera arrancada. init_db() aquí es defensa contra escenarios donde
# alguien sube el api SIN init.sql (ej. tests E2E contra una BD nueva
# sin el script). Si init.sql se ejecutó antes, create_all detecta las
# tablas existentes y no hace nada.
#
# CUIDADO: `set -e` aborta el script ante cualquier comando fallido.
# Es deliberado: si init_db falla, NO queremos que uvicorn arranque
# con BD inestable — el contenedor falla y docker lo reinicia.
set -e

echo "[entrypoint] Asegurando esquema de la base de datos…"
python -c "from app.db.session import init_db; init_db()"

# Acepta tres formas de "true" porque las variables de entorno suelen
# venir con casing variado (.env, docker-compose, kubectl set env...).
# Cualquier otro valor (false, "", "no", "0") deshabilita el seed.
# Default seguro: omitir seed. En producción JAMÁS debería tocarse.
SEED_FLAG="${SGCM_SEED:-false}"
if [ "$SEED_FLAG" = "true" ] || [ "$SEED_FLAG" = "TRUE" ] || [ "$SEED_FLAG" = "1" ]; then
    echo "[entrypoint] SGCM_SEED=$SEED_FLAG → ejecutando seed_db…"
    python -m app.scripts.seed_db
else
    echo "[entrypoint] SGCM_SEED=$SEED_FLAG → omitiendo seed (default seguro para producción)."
fi

# `exec "$@"` reemplaza el proceso del script por el CMD del Dockerfile
# (uvicorn). Sin exec, uvicorn quedaría como hijo del shell y las señales
# de docker stop no llegarían bien — el shutdown sería más lento y feo.
echo "[entrypoint] Arrancando proceso principal: $*"
exec "$@"
