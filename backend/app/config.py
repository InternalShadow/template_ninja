from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """Application configuration loaded from environment variables (prefix: RSB_)."""

    model_config = SettingsConfigDict(env_prefix="RSB_")

    app_name: str = "Resume Style Builder"
    data_dir: Path = _PROJECT_ROOT / "data"
    templates_dir: Path | None = None
    upload_max_size_mb: int = 10
    allowed_extensions: frozenset[str] = frozenset({".pdf"})
    cors_origins: list[str] = ["http://localhost:3000"]

    @model_validator(mode="after")
    def _resolve_templates_dir(self) -> "Settings":
        if self.templates_dir is None:
            self.templates_dir = self.data_dir / "templates_store"
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
