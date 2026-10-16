"""Dispatcher-level harness: real Dispatcher, stubbed Telegram HTTP session, in-memory FSM."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import GetMe, SendMessage, TelegramMethod
from aiogram.types import Chat, Message, MessageEntity, Update, User

from src.bot.dispatcher import create_dispatcher
from src.bot.i18n import create_translator_hub
from src.services.container import Services
from tests.helpers import add_allowed_user
from tests.stubs import StubReceiptParser


class RecordingSession(BaseSession):
    """Answers API calls with fake results and records them. No network."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[TelegramMethod[Any]] = []

    async def make_request(self, bot: Bot, method: TelegramMethod[Any], timeout: int | None = None):  # noqa: ASYNC109
        if isinstance(method, GetMe):
            return User(id=42, is_bot=True, first_name="Taler", username="taler_bot")
        self.calls.append(method)
        if isinstance(method, SendMessage):
            return Message(
                message_id=1,
                date=datetime.now(UTC),
                chat=Chat(id=int(method.chat_id), type="private"),
                text=method.text,
            )
        raise AssertionError(f"unexpected API call: {method!r}")

    async def stream_content(self, *args, **kwargs):  # pragma: no cover
        raise NotImplementedError
        yield b""

    async def close(self) -> None:
        pass


class BotHarness:
    def __init__(self, bot: Bot, dispatcher: Dispatcher, session: RecordingSession) -> None:
        self.bot = bot
        self.dispatcher = dispatcher
        self.session = session
        self._update_id = 0

    async def send_text(
        self, text: str, *, user_id: int, first_name: str = "Ann", username: str | None = "ann"
    ) -> None:
        self._update_id += 1
        entities = None
        if text.startswith("/"):
            command = text.split()[0]
            entities = [MessageEntity(type="bot_command", offset=0, length=len(command))]
        message = Message(
            message_id=self._update_id,
            date=datetime.now(UTC),
            chat=Chat(id=user_id, type="private"),
            from_user=User(id=user_id, is_bot=False, first_name=first_name, username=username),
            text=text,
            entities=entities,
        )
        await self.dispatcher.feed_update(
            self.bot, Update(update_id=self._update_id, message=message)
        )

    @property
    def sent_messages(self) -> list[SendMessage]:
        return [call for call in self.session.calls if isinstance(call, SendMessage)]


@pytest.fixture
async def harness(make_uow, tmp_storage) -> AsyncIterator[BotHarness]:
    recording = RecordingSession()
    bot = Bot("123456:TEST", session=recording)
    dispatcher = create_dispatcher(
        storage=MemoryStorage(),
        services=Services.build(make_uow, storage=tmp_storage, parser=StubReceiptParser()),
        translator_hub=create_translator_hub(),
    )
    yield BotHarness(bot, dispatcher, recording)
    await bot.session.close()


@pytest.fixture
def allow_user(make_uow):
    async def allow(user_id: int, *, first_name: str = "Ann", username: str | None = "ann"):
        await add_allowed_user(make_uow, user_id, first_name=first_name, username=username)

    return allow
