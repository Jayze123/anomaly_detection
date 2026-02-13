from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/anomaly_inspection"
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_expires_minutes: int = 120

    storage_root: str = "/data"

    camera_index: int = 0
    roi: str | None = None
    trigger_threshold: float = 0.08
    debounce_ms: int = 150

    @field_validator("storage_root")
    @classmethod
    def normalize_storage_root(cls, value: str) -> str:
        return str(Path(value))


@lru_cache
def get_settings() -> Settings:
    return Settings()
