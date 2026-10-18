from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.config.bot import BotConfig
from src.config.database import DatabaseConfig
from src.config.llm import LLMConfig
from src.config.redis import RedisConfig
from src.config.storage import StorageConfig

# Environment variables win over this file (see `.env.template` next to it).
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class _BaseSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
        # Models named `model_*` are fine: `llm.model` is a plain field.
        protected_namespaces=(),
    )

    @model_validator(mode="before")
    @classmethod
    def _validate_absent_sections(cls, data: Any) -> Any:
        # Without any of its env vars a section is absent and pydantic would only report the
        # section ("bot"). Validating it as empty names the missing field ("bot", "token").
        if isinstance(data, dict):
            for name, field in cls.model_fields.items():
                annotation = field.annotation
                if isinstance(annotation, type) and issubclass(annotation, BaseModel):
                    data.setdefault(name, {})
        return data


class DatabaseSettings(_BaseSettings):
    """Only the database section, so Alembic and tests run without bot secrets.

    Reads the same `DATABASE__URL` as `Settings.database`.
    """

    database: DatabaseConfig


_LOG_LEVELS = ("CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG")


class Settings(DatabaseSettings):
    log_level: str = "INFO"
    # Screens (messages opened by a command or a menu button) are deleted after this many
    # minutes without a tap; 0 switches expiry off. The sweeper checks every N seconds.
    screen_ttl_minutes: int = Field(default=30, ge=0)
    screen_sweep_seconds: int = Field(default=30, ge=1)
    bot: BotConfig
    redis: RedisConfig = RedisConfig()
    llm: LLMConfig
    storage: StorageConfig = StorageConfig()

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        name = value.strip().upper()
        if name not in _LOG_LEVELS:
            raise ValueError(f"LOG_LEVEL must be one of {', '.join(_LOG_LEVELS)}; got {value!r}")
        return name


@lru_cache
def get_settings() -> Settings:
    return Settings()  # pyright: ignore[reportCallIssue]  -- fields come from the environment
