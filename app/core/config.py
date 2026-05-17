"""Configuración centralizada del SGCM."""
from functools import lru_cache
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True, extra="ignore")

    # App
    APP_NAME: str = "SGCM"
    ENVIRONMENT: str = "production"
    API_V1_PREFIX: str = "/api/v1"

    # JWT
    JWT_SECRET_KEY: str = Field(..., min_length=32)
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # DB
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str
    POSTGRES_HOST: str = "db"
    POSTGRES_PORT: int = 5432

    BACKEND_CORS_ORIGINS: List[str] = ["http://localhost"]

    # Respaldos (CU-16)
    SGCM_BACKUP_LOCAL_DIR: str = "/var/backups/sgcm"
    SGCM_BACKUP_EXTERNAL_DIR: str = "/mnt/backup_externo"
    SGCM_BACKUP_S3_BUCKET: str = ""
    SGCM_BACKUP_S3_REGION: str = ""
    SGCM_BACKUP_GCS_BUCKET: str = ""
    SGCM_BACKUP_AZURE_CONTAINER: str = ""

    @property
    def DATABASE_URL(self) -> str:
        return (
            f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
