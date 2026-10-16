"""Settings are built from a controlled environment; the developer's real env file is never read."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from src.config.settings import ENV_FILE, DatabaseSettings, Settings

DB_URL = "postgresql+asyncpg://u:p@db:5432/app"

KEYS = [
    "BOT__TOKEN",
    "DATABASE__URL",
    "REDIS__URL",
    "LLM__MODEL",
    "LLM__API_KEY",
    "LLM__TIMEOUT_S",
    "STORAGE__RECEIPTS_DIR",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in KEYS:
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def full_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT__TOKEN", "123:bot-secret")
    monkeypatch.setenv("DATABASE__URL", DB_URL)
    monkeypatch.setenv("LLM__API_KEY", "sk-secret")


@pytest.mark.usefixtures("full_env")
def test_nested_values_load_from_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM__MODEL", "openai:other")
    monkeypatch.setenv("LLM__TIMEOUT_S", "30")
    monkeypatch.setenv("STORAGE__RECEIPTS_DIR", "/srv/receipts")

    settings = Settings(_env_file=None)

    assert settings.bot.token.get_secret_value() == "123:bot-secret"
    assert str(settings.database.url) == DB_URL
    assert settings.llm.api_key.get_secret_value() == "sk-secret"
    assert settings.llm.model == "openai:other"
    assert settings.llm.timeout_s == 30
    assert settings.storage.receipts_dir == Path("/srv/receipts")


@pytest.mark.usefixtures("full_env")
def test_defaults_for_optional_values() -> None:
    settings = Settings(_env_file=None)

    assert str(settings.redis.url) == "redis://localhost:6390/0"
    assert settings.llm.model == "openai:gpt-6-luna"
    assert settings.llm.timeout_s == 120
    assert settings.storage.receipts_dir == Path("data/receipts")


def test_env_file_is_used_and_env_vars_win(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "BOT__TOKEN=file-token\nDATABASE__URL=postgresql+asyncpg://f:f@file:5432/f\n"
        "LLM__API_KEY=file-key\nREDIS__URL=redis://file:6379/1\n"
    )
    monkeypatch.setenv("DATABASE__URL", DB_URL)

    settings = Settings(_env_file=env_file)

    assert str(settings.database.url) == DB_URL  # env var beats the file
    assert settings.bot.token.get_secret_value() == "file-token"  # file fills the rest
    assert str(settings.redis.url) == "redis://file:6379/1"


def test_missing_bot_token_names_the_field(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE__URL", DB_URL)
    monkeypatch.setenv("LLM__API_KEY", "sk-secret")

    with pytest.raises(ValidationError) as exc:
        Settings(_env_file=None)

    assert [e["loc"] for e in exc.value.errors()] == [("bot",)]
    assert "bot" in str(exc.value)


@pytest.mark.usefixtures("full_env")
def test_secrets_are_masked() -> None:
    settings = Settings(_env_file=None)

    text = f"{settings!r} {settings}"
    assert "bot-secret" not in text
    assert "sk-secret" not in text


def test_database_settings_need_only_the_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE__URL", DB_URL)

    assert str(DatabaseSettings(_env_file=None).database.url) == DB_URL


def test_database_settings_read_the_env_file_and_ignore_other_keys(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(f"DATABASE__URL={DB_URL}\nBOT__TOKEN=whatever\n")

    assert str(DatabaseSettings(_env_file=env_file).database.url) == DB_URL


def test_default_env_file_lives_in_the_config_package() -> None:
    assert ENV_FILE == Path("src/config/envs/.env").resolve()


def test_env_template_has_every_key_and_no_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    template = ENV_FILE.with_name(".env.template")
    values = dict(
        line.split("=", 1)
        for line in template.read_text().splitlines()
        if line and not line.startswith("#")
    )

    assert set(values) == set(KEYS)
    assert values["BOT__TOKEN"] == ""
    assert values["LLM__API_KEY"] == ""

    # With the two secrets filled in, the template is a valid configuration.
    for key, value in values.items():
        monkeypatch.setenv(key, value or "secret")
    assert Settings(_env_file=None).database.url
