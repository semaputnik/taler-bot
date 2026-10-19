"""Dispatcher-level harness: real Dispatcher, stubbed Telegram HTTP session, in-memory FSM."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import (
    AnswerCallbackQuery,
    DeleteMessage,
    EditMessageMedia,
    EditMessageReplyMarkup,
    EditMessageText,
    GetFile,
    GetMe,
    SendChatAction,
    SendMessage,
    SendPhoto,
    TelegramMethod,
)
from aiogram.types import (
    CallbackQuery,
    Chat,
    Document,
    File,
    InlineKeyboardMarkup,
    InputFile,
    Message,
    MessageEntity,
    PhotoSize,
    Update,
    User,
)
from aiogram_dialog.manager.updater import Updater

from src.bot.dispatcher import create_dispatcher
from src.bot.i18n import create_translator_hub
from src.bot.screens import MemoryScreenStore, ScreenRegistry
from src.bot.sweeper import ScreenSweeper
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
        self.sent_ids: list[int] = []  # the message id given to each SendMessage, in order
        self._next_message_id = 1000
        self.chat_action_fails = False  # make every `sendChatAction` raise
        self.rejected_file_ids: set[str] = set()  # file ids Telegram refuses to send as media
        self.undeletable_message_ids: set[int] = set()  # deleteMessage fails on these (48 h)
        self.rejected_calls: list[TelegramMethod[Any]] = []  # the media calls it refused
        self._uploads = 0
        self.photo_message_ids: set[int] = set()  # messages that currently hold a photo

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
        if isinstance(method, SendChatAction):
            if self.chat_action_fails:
                raise TelegramNetworkError(method=method, message="boom")
            return True
        if isinstance(method, SendMessage):
            self._next_message_id += 1
            self.sent_ids.append(self._next_message_id)
            return Message(
                message_id=self._next_message_id,
                date=datetime.now(UTC),
                chat=Chat(id=int(method.chat_id), type="private"),
                text=method.text,
            )
        if isinstance(method, SendPhoto):
            self._refuse_rejected(method, method.photo)
            self._next_message_id += 1
            self.sent_ids.append(self._next_message_id)
            self.photo_message_ids.add(self._next_message_id)
            return Message(
                message_id=self._next_message_id,
                date=datetime.now(UTC),
                chat=Chat(id=int(method.chat_id), type="private"),
                photo=[self._photo_size(method.photo)],
                caption=method.caption,
            )
        if isinstance(method, EditMessageMedia):
            self._refuse_rejected(method, getattr(method.media, "media", None))
            self.photo_message_ids.add(int(method.message_id or 0))
            return Message(
                message_id=int(method.message_id or 0),
                date=datetime.now(UTC),
                chat=Chat(id=int(method.chat_id or 0), type="private"),
                photo=[self._photo_size(getattr(method.media, "media", None))],
                caption=getattr(method.media, "caption", None),
            )
        if isinstance(method, EditMessageText):
            return Message(
                message_id=int(method.message_id or 0),
                date=datetime.now(UTC),
                chat=Chat(id=int(method.chat_id or 0), type="private"),
                text=method.text,
            )
        if isinstance(method, EditMessageReplyMarkup):
            return Message(
                message_id=int(method.message_id or 0),
                date=datetime.now(UTC),
                chat=Chat(id=int(method.chat_id or 0), type="private"),
            )
        if isinstance(method, DeleteMessage):
            if int(method.message_id) in self.undeletable_message_ids:
                raise TelegramBadRequest(method=method, message="message can't be deleted")
            self.photo_message_ids.discard(int(method.message_id))
            return True
        if isinstance(method, AnswerCallbackQuery):
            return True
        raise AssertionError(f"unexpected API call: {method!r}")

    def _refuse_rejected(self, method: TelegramMethod[Any], source: Any) -> None:
        if isinstance(source, str) and source in self.rejected_file_ids:
            self.rejected_calls.append(method)
            raise TelegramBadRequest(
                method=method, message="Bad Request: wrong file identifier/HTTP URL specified"
            )

    def _photo_size(self, source: Any) -> PhotoSize:
        """Telegram keeps a file id it was given; an uploaded file gets a new one."""
        if isinstance(source, InputFile):
            self._uploads += 1
            file_id = f"uploaded-{self._uploads}"
        else:
            file_id = str(source)
        return PhotoSize(file_id=file_id, file_unique_id=f"unique-{file_id}", width=800, height=600)

    async def stream_content(self, url: str, *args, **kwargs):
        """What `Bot.download_file` calls: the bytes registered for the file id in the URL."""
        file_id = url.rsplit("/", 1)[-1].removesuffix(".jpg")
        yield self.files.get(file_id, file_id.encode())

    async def close(self) -> None:
        pass


class FakeClock:
    """The registry's clock in tests: starts at a fixed time and moves only when told."""

    def __init__(self) -> None:
        self.now = 1_800_000_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, *, minutes: float) -> None:
        self.now += minutes * 60


class BotHarness:
    def __init__(
        self,
        bot: Bot,
        dispatcher: Dispatcher,
        session: RecordingSession,
        tasks: TaskRegistry,
        parser: StubReceiptParser,
        screens: ScreenRegistry,
        clock: FakeClock,
        sweeper: ScreenSweeper,
    ) -> None:
        self.screens = screens
        self.clock = clock
        self.sweeper = sweeper
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

    async def press(self, user_id: int, callback_data: str, message_id: int) -> None:
        """A tap on an inline button of the message `message_id` in the user's chat."""
        self._update_id += 1
        query = CallbackQuery(
            id=str(self._update_id),
            from_user=User(id=user_id, is_bot=False, first_name="Ann", username="ann"),
            chat_instance="test",
            message=Message(
                message_id=message_id,
                date=datetime.now(UTC),
                chat=Chat(id=user_id, type="private"),
                photo=[PhotoSize(file_id="shown", file_unique_id="shown", width=1, height=1)]
                if message_id in self.session.photo_message_ids
                else None,
            ),
            data=callback_data,
        )
        await self.dispatcher.feed_update(
            self.bot, Update(update_id=self._update_id, callback_query=query)
        )

    def keyboards(self) -> list[tuple[int, InlineKeyboardMarkup]]:
        """Every keyboard sent so far as (message id, keyboard), oldest first. A keyboard
        removed or replaced later shows up as its own entry (an empty one for a removal)."""
        found: list[tuple[int, InlineKeyboardMarkup]] = []
        sends = iter(self.session.sent_ids)
        for call in self.session.calls:
            if any(call is refused for refused in self.session.rejected_calls):
                continue  # Telegram refused it: no message, no keyboard
            if isinstance(call, SendMessage | SendPhoto):
                message_id = next(sends)
                if isinstance(call.reply_markup, InlineKeyboardMarkup):
                    found.append((message_id, call.reply_markup))
            elif isinstance(call, EditMessageText | EditMessageReplyMarkup | EditMessageMedia):
                markup = call.reply_markup
                found.append(
                    (int(call.message_id or 0), markup or InlineKeyboardMarkup(inline_keyboard=[]))
                )
        return found

    def last_text(self) -> str:
        """The text of the latest message sent or edited."""
        for call in reversed(self.session.calls):
            if isinstance(call, SendMessage | EditMessageText):
                return call.text
        raise AssertionError("nothing sent")

    def last_keyboard(self) -> tuple[int, InlineKeyboardMarkup]:
        return self.keyboards()[-1]

    def button_texts(self) -> list[str]:
        """The button labels of the latest keyboard."""
        return [b.text for row in self.last_keyboard()[1].inline_keyboard for b in row]

    async def tap(self, user_id: int, text: str) -> None:
        """Tap the button labelled `text` on the latest keyboard."""
        message_id, markup = self.last_keyboard()
        data = next(
            b.callback_data for row in markup.inline_keyboard for b in row if b.text == text
        )
        await self.press(user_id, data, message_id)

    async def sweep(self, *, after_minutes: float) -> None:
        """Move the clock on and run one sweep, as the sweeper task would."""
        self.clock.advance(minutes=after_minutes)
        await self.sweeper.sweep_once(self.clock.now)
        await self.tasks.drain()  # a closed dialog is a background update

    @property
    def deleted_messages(self) -> list[int]:
        return [int(c.message_id) for c in self.session.calls if isinstance(c, DeleteMessage)]

    @property
    def sent_messages(self) -> list[SendMessage]:
        return [call for call in self.session.calls if isinstance(call, SendMessage)]

    @property
    def sent_photos(self) -> list[SendPhoto]:
        return [call for call in self.session.calls if isinstance(call, SendPhoto)]

    @property
    def chat_actions(self) -> list[SendChatAction]:
        return [call for call in self.session.calls if isinstance(call, SendChatAction)]

    @property
    def get_file_calls(self) -> list[GetFile]:
        return [call for call in self.session.calls if isinstance(call, GetFile)]


@pytest.fixture
def screen_ttl_minutes() -> int:
    """Override in a module to change the TTL the harness' registry runs with."""
    return 30


@pytest.fixture
async def harness(
    make_uow, tmp_storage, monkeypatch, screen_ttl_minutes
) -> AsyncIterator[BotHarness]:
    recording = RecordingSession()
    bot = Bot("123456:TEST", session=recording)
    tasks = TaskRegistry()

    async def tracked_notify(self, bot, update) -> None:
        """A background dialog start (`bg.start`) runs as a fire-and-forget task; track it, so
        `tasks.drain()` waits for the card message too."""
        tasks.spawn(self._process_update(bot, update), name="dialog-update")

    monkeypatch.setattr(Updater, "notify", tracked_notify)
    parser = StubReceiptParser(default=output_of(fixture("03")["raw"]))
    clock = FakeClock()
    screens = ScreenRegistry(MemoryScreenStore(), ttl_minutes=screen_ttl_minutes, clock=clock)
    sweeper = ScreenSweeper(bot, screens, interval_seconds=30)
    dispatcher = create_dispatcher(
        storage=MemoryStorage(),
        services=Services.build(make_uow, storage=tmp_storage, parser=parser),
        translator_hub=create_translator_hub(),
        tasks=tasks,
        screens=screens,
        sweeper=sweeper,
    )
    yield BotHarness(bot, dispatcher, recording, tasks, parser, screens, clock, sweeper)
    await tasks.shutdown(1)
    await bot.session.close()


@pytest.fixture
def allow_user(make_uow):
    async def allow(user_id: int, *, first_name: str = "Ann", username: str | None = "ann"):
        await add_allowed_user(make_uow, user_id, first_name=first_name, username=username)

    return allow
