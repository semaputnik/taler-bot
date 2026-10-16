from functools import lru_cache
from pathlib import Path

from pydantic import PostgresDsn, RedisDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    """The part of the config that migrations need, so Alembic runs without bot secrets."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: PostgresDsn


class Settings(DatabaseSettings):
    bot_token: SecretStr
    openai_api_key: SecretStr
    redis_url: RedisDsn = RedisDsn("redis://localhost:6390/0")

    receipts_dir: Path = Path("data/receipts")
    llm_model: str = "openai:gpt-6-luna"
    llm_timeout_s: float = 120


@lru_cache
def get_settings() -> Settings:
    return Settings()  # pyright: ignore[reportCallIssue]  -- fields come from the environment
