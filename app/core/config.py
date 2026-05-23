"""Configuración centralizada del SGCM.

CONTEXTO: pydantic-settings lee variables del .env y del entorno. El
.env vive fuera de git por contener JWT_SECRET_KEY y la password de
PostgreSQL. En producción esas variables las inyecta docker-compose.

OJO: este módulo SE EVALÚA AL IMPORTAR (línea `settings = get_settings()`
al final). Si una variable obligatoria falta, el contenedor truena al
arrancar — eso es deliberado para fallar rápido en vez de seguir con
config rota.

CUIDADO: cualquier cosa que añadas aquí también debe estar reflejada
en el .env.example y, si es secreto, NO debe loggearse.
"""
from functools import lru_cache
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # case_sensitive=True: las variables del .env deben venir EXACTO en
    # mayúsculas. Si llegan en minúscula, pydantic-settings no las matchea
    # y truena por campo faltante. Es a propósito para evitar typos.
    # extra="ignore" tolera variables del entorno que no usamos (TZ, PATH,
    # etc.) sin levantar error.
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True, extra="ignore")

    # App
    APP_NAME: str = "SGCM"
    ENVIRONMENT: str = "production"
    API_V1_PREFIX: str = "/api/v1"

    # JWT
    # min_length=32 fuerza que la secret_key tenga entropía mínima para
    # HS256. Si en .env queda algo corto/débil, el contenedor falla al
    # arrancar — mejor que correr con una clave adivinable.
    JWT_SECRET_KEY: str = Field(..., min_length=32)
    JWT_ALGORITHM: str = "HS256"
    # 60 minutos: balance entre comodidad de la secretaria (no estar
    # re-logueando) y exposición si alguien deja la sesión abierta en
    # el consultorio. NO subirlo sin discutirlo con el HTQPJB.
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # DB
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str
    # Default "db" porque dentro de docker-compose el servicio postgres
    # se llama así. Para correr fuera de docker (debug local) hay que
    # exportar POSTGRES_HOST=localhost.
    POSTGRES_HOST: str = "db"
    POSTGRES_PORT: int = 5432

    # Por defecto solo permite http://localhost — el frontend pasa por
    # Nginx en el mismo origen y no necesita CORS. Si en algún momento
    # el frontend se separa a otro dominio, hay que agregarlo aquí.
    BACKEND_CORS_ORIGINS: List[str] = ["http://localhost"]

    # Respaldos (CU-16)
    # Las cuatro rutas y los buckets son donde caen los .sql generados.
    # Los stubs de nube usan estos valores como configuración cuando
    # se activen los SDK respectivos (ver app/services/backup/nube/).
    SGCM_BACKUP_LOCAL_DIR: str = "/var/backups/sgcm"
    SGCM_BACKUP_EXTERNAL_DIR: str = "/mnt/backup_externo"
    SGCM_BACKUP_S3_BUCKET: str = ""
    SGCM_BACKUP_S3_REGION: str = ""
    SGCM_BACKUP_GCS_BUCKET: str = ""
    SGCM_BACKUP_AZURE_CONTAINER: str = ""

    @property
    def DATABASE_URL(self) -> str:
        # psycopg2 (no psycopg3): por requirements.txt. Si se migra a
        # psycopg3, también hay que cambiar el prefijo a postgresql+psycopg.
        return (
            f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


@lru_cache
def get_settings() -> Settings:
    # lru_cache hace que Settings() solo se instancie una vez por proceso.
    # Útil para tests que importan settings desde varios lados.
    return Settings()


# Singleton de módulo. La mayoría del código importa `settings` directo
# en vez de llamar a get_settings() — funciona porque ambas referencias
# apuntan al mismo objeto cacheado.
settings = get_settings()
