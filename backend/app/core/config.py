from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = "Ingenia AI"

    host: str = Field("127.0.0.1", validation_alias=AliasChoices("INGENIA_HOST", "HOST"))
    port: int = Field(8000, validation_alias=AliasChoices("INGENIA_PORT", "PORT"))

    auth_token: str = Field(
        "ingenia-local-dev",
        validation_alias=AliasChoices("INGENIA_AUTH_TOKEN", "AUTH_TOKEN"),
    )
    allow_remote: bool = Field(
        False, validation_alias=AliasChoices("INGENIA_ALLOW_REMOTE")
    )
    cookie_secure: bool = Field(
        False, validation_alias=AliasChoices("INGENIA_COOKIE_SECURE")
    )

    ollama_url: str = Field(
        "http://127.0.0.1:11434", validation_alias=AliasChoices("OLLAMA_URL")
    )
    ollama_model: str = Field(
        "qwen2.5-coder:1.5b", validation_alias=AliasChoices("OLLAMA_MODEL")
    )
    ollama_timeout: float = Field(
        300.0, validation_alias=AliasChoices("OLLAMA_TIMEOUT")
    )

    civil3d_bridge_url: str = Field(
        "http://127.0.0.1:8756",
        validation_alias=AliasChoices("CIVIL3D_BRIDGE_URL"),
    )
    civil3d_token: str = Field("", validation_alias=AliasChoices("CIVIL3D_TOKEN"))
    civil3d_fallback_to_mock: bool = Field(
        True, validation_alias=AliasChoices("CIVIL3D_FALLBACK_TO_MOCK")
    )
    civil3d_timeout: float = Field(
        30.0, validation_alias=AliasChoices("CIVIL3D_TIMEOUT")
    )

    database_path: str = Field("", validation_alias=AliasChoices("DATABASE_PATH"))
    rate_limit_per_minute: int = Field(
        120, validation_alias=AliasChoices("RATE_LIMIT_PER_MINUTE")
    )
    max_tool_steps: int = Field(
        4, validation_alias=AliasChoices("MAX_TOOL_STEPS")
    )

    @property
    def db_path(self) -> Path:
        if self.database_path:
            return Path(self.database_path).expanduser()
        return BACKEND_DIR / "data" / "ingenia.db"

    @property
    def frontend_dir(self) -> Path:
        return PROJECT_ROOT / "frontend"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
