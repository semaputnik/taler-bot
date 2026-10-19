import asyncio
from types import SimpleNamespace

from src.bot import app as app_module
from src.bot.app import App
from src.config.bot import BotConfig
from src.config.database import DatabaseConfig
from src.config.llm import LLMConfig
from src.config.settings import Settings
from src.domain.receipt import Receipt
from src.services.container import Services
from tests.bot.conftest import RecordingSession
from tests.domain.builders import photo
from tests.helpers import add_allowed_user
from tests.stubs import StubReceiptParser


async def test_lifespan_closes_the_bot_session_on_exit():
    session = RecordingSession()
    closed = []

    async def close() -> None:
        closed.append(True)

    session.close = close
    settings = Settings(
        _env_file=None,
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
        _env_file=None,
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
    app.engine = SimpleNamespace(dispose=record_engine)

    async with app.lifespan():
        pass

    assert closed == ["storage", "engine"]


async def test_lifespan_closes_the_receipt_parser():
    settings = Settings(
        _env_file=None,
        bot=BotConfig(token="123456:TEST"),
        database=DatabaseConfig(url="postgresql+asyncpg://u:p@localhost:1/db"),
        llm=LLMConfig(api_key="x"),
    )
    app = App(settings, bot_session=RecordingSession())

    async with app.lifespan():
        assert not app.receipt_parser._client.is_closed()

    assert app.receipt_parser._client.is_closed()


async def test_lifespan_with_a_pending_task_finishes_within_the_timeout(monkeypatch):
    monkeypatch.setattr(app_module, "TASK_SHUTDOWN_TIMEOUT", 0.05)
    settings = Settings(
        _env_file=None,
        bot=BotConfig(token="123456:TEST"),
        database=DatabaseConfig(url="postgresql+asyncpg://u:p@localhost:1/db"),
        llm=LLMConfig(api_key="x"),
    )
    app = App(settings, bot_session=RecordingSession())
    cancelled = []

    async def forever() -> None:
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            cancelled.append(True)
            raise

    async with app.lifespan():
        app.tasks.spawn(forever(), name="forever")
        await asyncio.sleep(0)

    assert cancelled == [True]


async def test_run_recovers_receipts_left_parsing_before_polling_starts(make_uow, tmp_storage):
    await add_allowed_user(make_uow, 1)
    async with make_uow() as uow:
        receipt = await uow.receipts.add(Receipt.start(1, photo("stuck")))
        receipt.mark_parsing()
        await uow.receipts.save(receipt)
        await uow.commit()
    settings = Settings(
        _env_file=None,
        bot=BotConfig(token="123456:TEST"),
        database=DatabaseConfig(url="postgresql+asyncpg://u:p@localhost:1/db"),
        llm=LLMConfig(api_key="x"),
    )
    app = App(settings, bot_session=RecordingSession())
    app.services = Services.build(make_uow, storage=tmp_storage, parser=StubReceiptParser())
    seen = []

    async def polling(bot, **kwargs) -> None:
        async with make_uow() as uow:
            stored = await uow.receipts.get(receipt.id)
        seen.append((stored.status, stored.error_message))

    app.dispatcher.start_polling = polling

    await app.run()

    assert seen == [("failed", "interrupted")]


def _settings(**extra) -> Settings:
    return Settings(
        _env_file=None,
        bot=BotConfig(token="123456:TEST"),
        database=DatabaseConfig(url="postgresql+asyncpg://u:p@localhost:1/db"),
        llm=LLMConfig(api_key="x"),
        **extra,
    )


async def test_lifespan_spawns_the_screen_sweeper_and_cancels_it_on_exit():
    app = App(_settings(screen_ttl_minutes=30), bot_session=RecordingSession())

    async with app.lifespan():
        assert app.tasks.is_running("screens-sweeper")
        (task,) = [t for t in app.tasks._tasks if t.get_name() == "screens-sweeper"]

    assert task.cancelled()
    assert not app.tasks.is_running("screens-sweeper")


async def test_lifespan_spawns_no_sweeper_when_the_ttl_is_zero():
    app = App(_settings(screen_ttl_minutes=0), bot_session=RecordingSession())

    async with app.lifespan():
        assert not app.tasks.is_running("screens-sweeper")


async def test_lifespan_closes_the_screens_redis_client():
    app = App(_settings(), bot_session=RecordingSession())
    closed = []

    async def close() -> None:
        closed.append(True)

    app.redis.aclose = close

    async with app.lifespan():
        pass

    assert closed == [True]
