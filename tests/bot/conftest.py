"""Dispatcher-level harness: real Dispatcher, stubbed Telegram HTTP session, in-memory FSM."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import GetFile, GetMe, SendMessage, TelegramMethod
from aiogram.types import (
    Chat,
    Document,
    File,
    Message,
    MessageEntity,
    PhotoSize,
    Update,
    User,
)

from src.bot.dispatcher import create_dispatcher
from src.bot.i18n import create_translator_hub
from src.bot.tasks import TaskRegistry
from src.services.container import Services
from tests.helpers import add_allowed_user
from tests.stubs import StubReceiptParser, fixture, output_of


class RecordingSession(BaseSession):
    """Answers API calls with fake results and records them. No network."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[TelegramMethod[Any]] = []
        self.files: dict[str, bytes] = {}  # file_id -> bytes served by `download_file`

    async def make_request(self, bot: Bot, method: TelegramMethod[Any], timeout: int | None = None):  # noqa: ASYNC109
        if isinstance(method, GetMe):
            return User(id=42, is_bot=True, first_name="Taler", username="taler_bot")
        self.calls.append(method)
        if isinstance(method, GetFile):
            return File(
                file_id=method.file_id,
                file_unique_id=f"unique-{method.file_id}",
                file_path=f"photos/{method.file_id}.jpg",
                file_size=len(self.files.get(method.file_id, b"")),
            )
        if isinstance(method, SendMessage):
            return Message(
                message_id=1,
                date=datetime.now(UTC),
                chat=Chat(id=int(method.chat_id), type="private"),
                text=method.text,
            )
        raise AssertionError(f"unexpected API call: {method!r}")

    async def stream_content(self, url: str, *args, **kwargs):
        """What `Bot.download_file` calls: the bytes registered for the file id in the URL."""
        file_id = url.rsplit("/", 1)[-1].removesuffix(".jpg")
        yield self.files.get(file_id, file_id.encode())

    async def close(self) -> None:
        pass


class BotHarness:
    def __init__(
        self,
        bot: Bot,
        dispatcher: Dispatcher,
        session: RecordingSession,
        tasks: TaskRegistry,
        parser: StubReceiptParser,
    ) -> None:
        self.bot = bot
        self.dispatcher = dispatcher
        self.session = session
        self.tasks = tasks
        self.parser = parser
        self._update_id = 0

    async def _feed(self, user_id: int, **fields: Any) -> int:
        self._update_id += 1
        message = Message(
            message_id=self._update_id,
            date=datetime.now(UTC),
            chat=Chat(id=user_id, type="private"),
            from_user=User(id=user_id, is_bot=False, first_name="Ann", username="ann"),
            **fields,
        )
        await self.dispatcher.feed_update(
            self.bot, Update(update_id=self._update_id, message=message)
        )
        return message.message_id

    async def send_photo(
        self, *, user_id: int, file_id: str = "f1", data: bytes | None = None, unique_id: str = ""
    ) -> int:
        """A compressed photo (two sizes, the largest last). Returns its message id."""
        if data is not None:
            self.session.files[file_id] = data
        unique_id = unique_id or f"unique-{file_id}"
        sizes = [
            PhotoSize(file_id=f"small-{file_id}", file_unique_id="s", width=90, height=90),
            PhotoSize(file_id=file_id, file_unique_id=unique_id, width=1280, height=960),
        ]
        return await self._feed(user_id, photo=sizes)

    async def send_document(
        self,
        *,
        user_id: int,
        mime_type: str | None,
        file_id: str = "d1",
        unique_id: str = "",
        file_size: int | None = 1000,
        data: bytes | None = None,
    ) -> int:
        if data is not None:
            self.session.files[file_id] = data
        document = Document(
            file_id=file_id,
            file_unique_id=unique_id or f"unique-{file_id}",
            mime_type=mime_type,
            file_size=file_size,
        )
        return await self._feed(user_id, document=document)

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

    @property
    def get_file_calls(self) -> list[GetFile]:
        return [call for call in self.session.calls if isinstance(call, GetFile)]


@pytest.fixture
async def harness(make_uow, tmp_storage) -> AsyncIterator[BotHarness]:
    recording = RecordingSession()
    bot = Bot("123456:TEST", session=recording)
    tasks = TaskRegistry()
    parser = StubReceiptParser(default=output_of(fixture("03")["raw"]))
    dispatcher = create_dispatcher(
        storage=MemoryStorage(),
        services=Services.build(make_uow, storage=tmp_storage, parser=parser),
        translator_hub=create_translator_hub(),
        tasks=tasks,
    )
    yield BotHarness(bot, dispatcher, recording, tasks, parser)
    await tasks.shutdown(1)
    await bot.session.close()


@pytest.fixture
def allow_user(make_uow):
    async def allow(user_id: int, *, first_name: str = "Ann", username: str | None = "ann"):
        await add_allowed_user(make_uow, user_id, first_name=first_name, username=username)

    return allow
