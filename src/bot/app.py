import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import DefaultKeyBuilder, RedisStorage

from src.bot.dispatcher import create_dispatcher
from src.bot.i18n import create_translator_hub
from src.bot.usecases import UseCases
from src.config.settings import Settings
from src.database.engine import create_engine, create_sessionmaker
from src.database.uow.sqlalchemy import SqlAlchemyUnitOfWork

logger = logging.getLogger(__name__)


class App:
    """Owns every long-lived object. They are created once here, never per update."""

    def __init__(self, settings: Settings, *, bot_session: BaseSession | None = None) -> None:
        self.settings = settings
        self.bot = Bot(
            settings.bot.token.get_secret_value(),
            session=bot_session,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        self.engine = create_engine(settings)
        session_factory = create_sessionmaker(self.engine)
        self.storage = RedisStorage.from_url(
            str(settings.redis.url), key_builder=DefaultKeyBuilder(with_destiny=True)
        )
        self.translator_hub = create_translator_hub()
        self.usecases = UseCases.build(lambda: SqlAlchemyUnitOfWork(session_factory))
        self.dispatcher = create_dispatcher(
            storage=self.storage, usecases=self.usecases, translator_hub=self.translator_hub
        )

    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator[None]:
        try:
            yield
        finally:
            logger.info("Shutting down")
            # Each resource is closed even if an earlier close fails.
            for name, close in (
                ("bot session", self.bot.session.close),
                ("storage", self.storage.close),
                ("engine", self.engine.dispose),
            ):
                try:
                    await close()
                except Exception:
                    logger.exception("Failed to close %s", name)

    async def run(self) -> None:
        """Long polling until Ctrl+C / SIGTERM (aiogram handles the signals)."""
        async with self.lifespan():
            await self.dispatcher.start_polling(self.bot, close_bot_session=False)
