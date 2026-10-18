"""A stored receipt photo as dialog media: by Telegram file id, uploaded only if that is refused.

aiogram-dialog lets a `TelegramBadRequest` on sending media escape. `StoredPhotoMessageManager`
catches it for a `StoredPhoto` and retries once with the bytes the attachment can load, for that
message only. If the bytes cannot be loaded either, the message shows the attachment's notice
text instead of the photo.

It also tracks the manual entry's message as an expiring screen (see `show_message`).

It also keeps the keyboards of older cards (receipt and expense) when a new card is sent.
"""

import logging
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import replace

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.state import StatesGroup
from aiogram.types import BufferedInputFile, ContentType, InputFile, Message
from aiogram_dialog import ShowMode
from aiogram_dialog.api.entities import MediaAttachment, MediaId, NewMessage, OldMessage
from aiogram_dialog.api.protocols import MessageNotModified
from aiogram_dialog.manager.message_manager import MessageManager

from src.bot.keyboards.cards import is_card_markup
from src.bot.screens import Screen, ScreenKind, ScreenRegistry
from src.bot.states.expense_card import ExpenseCardSG
from src.bot.states.expense_entry import ExpenseEntrySG
from src.bot.states.receipt_card import ReceiptCardSG
from src.integration.storage import StorageError

logger = logging.getLogger(__name__)

_keep_previous_keyboard: ContextVar[bool] = ContextVar("keep_previous_keyboard", default=False)


@contextmanager
def keeping_previous_keyboard() -> Iterator[None]:
    """While active, sending a dialog message leaves the previous message's keyboard alone."""
    token = _keep_previous_keyboard.set(True)
    try:
        yield
    finally:
        _keep_previous_keyboard.reset(token)


_track_card: ContextVar[bool] = ContextVar("track_card", default=False)


@contextmanager
def tracking_card() -> Iterator[None]:
    """While active, a card message that the dialog shows is tracked as an expiring screen.
    Set around a card the user asked for (a history row, a copy of an older card); a card the
    bot sent by itself (after a parse or an entry) is never tracked."""
    token = _track_card.set(True)
    try:
        yield
    finally:
        _track_card.reset(token)


# The state group of the dialog being shown; set by `TrackingManager.show`, read by the message
# manager, which is not told which dialog a message belongs to.
showing_group: ContextVar[type[StatesGroup] | None] = ContextVar("showing_group", default=None)

# Errors about the message being edited, not about the media; they are not a refused file id.
_EDIT_ERRORS = ("message is not modified", "message can't be edited", "message to edit not found")


def _entry_screen(message: OldMessage) -> Screen:
    return Screen(message.chat.id, message.message_id, ScreenKind.ENTRY)


def _plain_screen(message: OldMessage) -> Screen:
    return Screen(message.chat.id, message.message_id, ScreenKind.PLAIN)


_CARD_GROUPS = (ReceiptCardSG, ExpenseCardSG)


class StoredPhoto(MediaAttachment):
    """A photo known by its Telegram file id (maybe unknown), with a way to load its bytes."""

    def __init__(
        self,
        file_id: str | None,
        load_bytes: Callable[[], Awaitable[bytes]],
        unavailable_text: str,
    ) -> None:
        # No path or URL: aiogram-dialog's media id cache keys on those and must not see this.
        super().__init__(ContentType.PHOTO, file_id=MediaId(file_id or ""))
        self.load_bytes = load_bytes
        self.unavailable_text = unavailable_text
        self.data: bytes | None = None  # set when the file id was refused

    @property
    def has_file_id(self) -> bool:
        return bool(self.file_id and self.file_id.file_id)


class StoredPhotoMessageManager(MessageManager):
    def __init__(self, screens: ScreenRegistry | None = None) -> None:
        self._screens = screens

    async def show_message(
        self, bot: Bot, new_message: NewMessage, old_message: OldMessage | None
    ) -> OldMessage:
        """The one place that sees every dialog message: the manual entry's message is tracked
        as an expiring screen, and every show of it (a tap or a typed value) moves its time."""
        screens = self._screens
        group = showing_group.get()
        if screens is None or not screens.enabled:
            return await super().show_message(bot, new_message, old_message)
        if group in _CARD_GROUPS:
            return await self._show_card(screens, bot, new_message, old_message)
        if group is not ExpenseEntrySG:
            return await super().show_message(bot, new_message, old_message)
        try:
            sent = await super().show_message(bot, new_message, old_message)
        except MessageNotModified:
            if old_message is not None:
                await screens.touch(_entry_screen(old_message))
            raise
        if old_message is not None and old_message.message_id != sent.message_id:
            await screens.forget(_entry_screen(old_message))
        await screens.track(_entry_screen(sent))
        return sent

    async def _show_card(
        self,
        screens: ScreenRegistry,
        bot: Bot,
        new_message: NewMessage,
        old_message: OldMessage | None,
    ) -> OldMessage:
        """A card the user asked for (`tracking_card`) expires; any later show of it moves its
        time. A card nobody tracked (from a parse or an entry) stays as it is."""
        try:
            sent = await super().show_message(bot, new_message, old_message)
        except MessageNotModified:
            if old_message is not None:
                await screens.touch(_plain_screen(old_message))
            raise
        if _track_card.get():
            await screens.track(_plain_screen(sent))
        elif (
            old_message is not None
            and new_message.show_mode is not ShowMode.SEND  # SEND leaves the old message alone
            and old_message.message_id != sent.message_id
        ):
            # The old card was replaced (e.g. the photo window): a tracked card stays tracked.
            await screens.move(_plain_screen(old_message), _plain_screen(sent))
        else:
            await screens.touch(_plain_screen(sent))
        return sent

    async def _remove_kbd(
        self, bot: Bot, old_message: OldMessage | None, new_message: NewMessage | None
    ) -> Message | None:
        """aiogram-dialog strips the previous message's keyboard whenever it sends a new one.
        A new receipt card, or a window opened from an older card, must not do that: the older
        cards keep their buttons."""
        if _keep_previous_keyboard.get() or (
            new_message is not None and is_card_markup(new_message.reply_markup)
        ):
            return None
        return await super()._remove_kbd(bot, old_message, new_message)

    async def get_media_source(self, media: MediaAttachment, bot: Bot) -> InputFile | str:
        if isinstance(media, StoredPhoto) and media.data is not None:
            return BufferedInputFile(media.data, filename="receipt.jpg")
        return await super().get_media_source(media, bot)

    async def send_media(self, bot: Bot, new_message: NewMessage) -> Message:
        media = new_message.media
        if not isinstance(media, StoredPhoto):
            return await super().send_media(bot, new_message)
        try:
            return await self._with_bytes_fallback(media, super().send_media, bot, new_message)
        except StorageError:
            return await self._send_notice(bot, new_message, media)

    async def edit_media(
        self, bot: Bot, new_message: NewMessage, old_message: OldMessage
    ) -> Message:
        media = new_message.media
        if not isinstance(media, StoredPhoto):
            return await super().edit_media(bot, new_message, old_message)
        try:
            return await self._with_bytes_fallback(
                media, super().edit_media, bot, new_message, old_message
            )
        except StorageError:
            # The old message may hold a photo, which cannot be edited into text.
            await self.remove_message_safe(bot, old_message, new_message)
            return await self._send_notice(bot, new_message, media)

    async def _with_bytes_fallback(
        self, media: StoredPhoto, call: Callable[..., Awaitable[Message]], *args
    ) -> Message:
        if media.has_file_id:
            try:
                return await call(*args)
            except TelegramBadRequest as error:
                if any(marker in error.message.lower() for marker in _EDIT_ERRORS):
                    raise
                logger.info("Telegram refused the stored file id: %s", error.message)
        media.data = await media.load_bytes()  # raises StorageError
        return await call(*args)

    async def _send_notice(self, bot: Bot, new_message: NewMessage, media: StoredPhoto) -> Message:
        return await self.send_text(
            bot, replace(new_message, media=None, text=media.unavailable_text)
        )
