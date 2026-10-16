from src.bot.app import App
from src.config.bot import BotConfig
from src.config.database import DatabaseConfig
from src.config.llm import LLMConfig
from src.config.settings import Settings
from tests.bot.conftest import RecordingSession


async def test_lifespan_closes_the_bot_session_on_exit():
    session = RecordingSession()
    closed = []

    async def close() -> None:
        closed.append(True)

    session.close = close
    settings = Settings(
        bot=BotConfig(token="123456:TEST"),
        database=DatabaseConfig(url="postgresql+asyncpg://u:p@localhost:1/db"),
        llm=LLMConfig(api_key="x"),
    )
    app = App(settings, bot_session=session)

    async with app.lifespan():
        assert closed == []

    assert closed == [True]


async def test_lifespan_closes_storage_and_engine_even_if_the_bot_session_fails():
    session = RecordingSession()
    closed = []

    async def failing_close() -> None:
        raise RuntimeError("boom")

    session.close = failing_close
    settings = Settings(
        bot=BotConfig(token="123456:TEST"),
        database=DatabaseConfig(url="postgresql+asyncpg://u:p@localhost:1/db"),
        llm=LLMConfig(api_key="x"),
    )
    app = App(settings, bot_session=session)

    async def record_storage() -> None:
        closed.append("storage")

    async def record_engine() -> None:
        closed.append("engine")

    app.storage.close = record_storage
    app.engine.dispose = record_engine

    async with app.lifespan():
        pass

    assert closed == ["storage", "engine"]
