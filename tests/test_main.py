"""`python -m src` fails fast with the env var names of what is missing."""

from functools import partial

import pytest

from src import __main__ as entrypoint
from src.config.settings import Settings
from tests.test_settings import KEYS


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(entrypoint, "Settings", partial(Settings, _env_file=None))


def test_missing_settings_are_reported_as_env_var_names(caplog: pytest.LogCaptureFixture) -> None:
    assert entrypoint.main() == 1
    assert "BOT__TOKEN" in caplog.text
    assert "DATABASE__URL" in caplog.text
    assert "LLM__API_KEY" in caplog.text


def test_empty_bot_token_is_rejected(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("BOT__TOKEN", "")
    monkeypatch.setenv("DATABASE__URL", "postgresql+asyncpg://u:p@db:5432/app")
    monkeypatch.setenv("LLM__API_KEY", "sk")

    assert entrypoint.main() == 1
    assert "BOT__TOKEN is empty" in caplog.text
