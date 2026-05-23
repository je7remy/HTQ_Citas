# Imagen base oficial de Python — versión slim para reducir tamaño.
# 3.11 alineado con lo declarado en pyproject/CI (no usar 3.12 sin
# verificar que weasyprint/jose/sqlmodel sigan compatibles).
FROM python:3.11-slim

# PYTHONDONTWRITEBYTECODE: no genera .pyc dentro del contenedor — no
#   los necesitamos (sin caché persistente entre runs).
# PYTHONUNBUFFERED: stdout/stderr salen sin buffer para que docker logs
#   muestre los logs en tiempo real.
# PIP_NO_CACHE_DIR: imagen más liviana (sin caché de wheels).
# TZ: imprescindible — todo el SGCM depende de America/Santo_Domingo.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=America/Santo_Domingo

# Dependencias de sistema para WeasyPrint + psycopg2 + pg_dump + zona horaria RD
# Por qué cada una:
#   build-essential + libpq-dev + libffi-dev: compilación de psycopg2/bcrypt.
#   postgresql-client: aporta pg_dump (CU-16, módulo de respaldos).
#   libpango/cairo/gdk-pixbuf/harfbuzz/shared-mime-info: stack gráfico
#     de WeasyPrint para renderizar PDFs con fuentes y SVG correctos.
#   fonts-liberation: tipografía base de los reportes (sin esto los
#     PDFs salen con typewriter feo o caracteres faltantes).
#   tzdata + ln + reconfigure: deja el reloj del contenedor en RD.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    postgresql-client \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libharfbuzz0b \
    libcairo2 \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    shared-mime-info \
    fonts-liberation \
    tzdata \
    && ln -fs /usr/share/zoneinfo/America/Santo_Domingo /etc/localtime \
    && dpkg-reconfigure -f noninteractive tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Truco de caché: copiar SOLO requirements.txt primero, instalar deps,
# y luego copiar el código. Mientras requirements.txt no cambie, la
# capa de pip install se reusa entre builds — ahorra varios minutos
# en cada rebuild incremental.
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

# Directorio para respaldos locales (CU-16). Si se monta un volumen sobre
# esta ruta, el volumen toma precedencia; este RUN solo garantiza la
# existencia y los permisos en builds sin volumen.
RUN mkdir -p /var/backups/sgcm && chmod 755 /var/backups/sgcm

# El entrypoint inicializa el esquema y, si SGCM_SEED=true, ejecuta el seeder.
RUN chmod +x /app/docker-entrypoint.sh

EXPOSE 8000

# ENTRYPOINT inicializa el esquema y opcionalmente siembra. CMD es el
# proceso que el entrypoint exec'a al final (uvicorn).
# 2 workers: balance entre uso de RAM (~150MB por worker con WeasyPrint)
# y concurrencia para el volumen del HTQPJB. Subir a 4 si la planta
# crece, bajar a 1 si la RAM es escasa.
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
