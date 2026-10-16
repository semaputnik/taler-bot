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
from src.bot.tasks import TaskRegistry
from src.config.settings import Settings
from src.database.engine import create_engine, create_sessionmaker
from src.database.uow.sqlalchemy import SqlAlchemyUnitOfWork
from src.integration.llm import OpenAIReceiptParser
from src.integration.storage import LocalPhotoStorage
from src.services.container import Services

logger = logging.getLogger(__name__)

TASK_SHUTDOWN_TIMEOUT = 10.0


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
        self.photo_storage = LocalPhotoStorage(settings.storage.receipts_dir)
        self.receipt_parser = OpenAIReceiptParser(settings.llm)
        self.services = Services.build(
            lambda: SqlAlchemyUnitOfWork(session_factory),
            storage=self.photo_storage,
            parser=self.receipt_parser,
        )
        self.tasks = TaskRegistry()
        self.dispatcher = create_dispatcher(
            storage=self.storage,
            services=self.services,
            translator_hub=self.translator_hub,
            tasks=self.tasks,
        )

    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator[None]:
        try:
            yield
        finally:
            logger.info("Shutting down")
            # Each resource is closed even if an earlier close fails.
            for name, close in (
                ("background tasks", lambda: self.tasks.shutdown(TASK_SHUTDOWN_TIMEOUT)),
                ("bot session", self.bot.session.close),
                ("receipt parser", self.receipt_parser.close),
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
