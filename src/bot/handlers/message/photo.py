"""Photo intake: save the photo, answer at once, read it in the background, answer again.

The photo handler is included before the dialogs (a dialog's message handler takes every
message sent while it is open, so a photo would never get through); the catch-all "send me a
photo" is included after them, so it never swallows a dialog's text input.
"""

import logging
from html import escape
from zoneinfo import ZoneInfo

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup, Message, ReplyParameters
from aiogram.utils.chat_action import ChatActionSender
from fluentogram import TranslatorRunner

from src.bot import render
from src.bot.keyboards.receipt import receipt_keyboard
from src.bot.tasks import TaskRegistry
from src.exception import DuplicatePhoto
from src.services.container import Services
from src.services.results import CurrentUser, NewPhoto, ParseResult

logger = logging.getLogger(__name__)

MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024  # the Bot API cannot serve bigger files
TYPING_INTERVAL = 4.0  # seconds; Telegram shows "typing" for about 5 s after each action


async def photo_intake(
    message: Message,
    bot: Bot,
    user: CurrentUser,
    services: Services,
    tasks: TaskRegistry,
    i18n: TranslatorRunner,
) -> None:
    if message.photo:
        attachment = message.photo[-1]  # the largest size is last
        mime_type = "image/jpeg"
    else:
        attachment = message.document
        mime_type = attachment.mime_type if attachment else None
        if attachment is None or not (mime_type or "").startswith("image/"):
            await message.reply(i18n.get("photo-send-me-one"))
            return

    if (attachment.file_size or 0) > MAX_DOWNLOAD_BYTES:
        await message.reply(i18n.get("photo-too-large"))
        return
    try:
        file = await bot.get_file(attachment.file_id)
        if file.file_path is None:  # Telegram gives no path for files it will not serve
            await message.reply(i18n.get("photo-too-large"))
            return
        buffer = await bot.download_file(file.file_path)
    except TelegramBadRequest as error:
        if "too big" not in str(error):
            raise
        await message.reply(i18n.get("photo-too-large"))
        return
    data = buffer.read() if buffer is not None else b""

    new_photo = NewPhoto(
        received_at=message.date,
        telegram_file_id=attachment.file_id,
        telegram_file_unique_id=attachment.file_unique_id,
        telegram_message_id=message.message_id,
        mime_type=mime_type,
        size_bytes=len(data),
    )
    try:
        card = await services.receipts.save_photo(user.id, data, new_photo)
    except DuplicatePhoto:
        await message.reply(i18n.get("photo-already-have"))
        return

    await _send(bot, message.chat.id, message.message_id, i18n.get("receipt-saved"))
    tasks.spawn(
        _parse_and_reply(
            bot,
            message.chat.id,
            message.message_id,
            user.id,
            card.receipt_id,
            services,
            i18n,
            user.timezone,
        ),
        name=f"parse-receipt-{card.receipt_id}",
    )


async def not_a_photo(message: Message, i18n: TranslatorRunner) -> None:
    await message.reply(i18n.get("photo-send-me-one"))


async def _parse_and_reply(
    bot: Bot,
    chat_id: int,
    reply_to: int,
    user_id: int,
    receipt_id: int,
    services: Services,
    i18n: TranslatorRunner,
    tz: str,
) -> None:
    """Parse, then send exactly one reply. Nothing but cancellation leaves this function."""
    item_count = 0
    try:
        # The sender's worker dies on a failed `sendChatAction` and the block still ends
        # normally, so the typing status never affects the parse or the reply.
        async with ChatActionSender.typing(bot=bot, chat_id=chat_id, interval=TYPING_INTERVAL):
            result = await services.receipts.parse(user_id, receipt_id)
        text = _render(result, i18n, ZoneInfo(tz))
        # Only a parsed receipt offers its items; a duplicate keeps its own, but is inspected
        # and deleted, not browsed.
        item_count = result.card.item_count if result.outcome == "parsed" else 0
    except Exception:
        # The service has already marked the receipt failed; the user must not wait for nothing.
        logger.exception("Parsing receipt %s failed", receipt_id)
        text = i18n.get("receipt-failed")
    await _send(
        bot, chat_id, reply_to, text, receipt_keyboard(i18n, receipt_id, item_count=item_count)
    )


async def _send(
    bot: Bot,
    chat_id: int,
    reply_to: int,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    """A Telegram failure is logged, never raised into the caller."""
    try:
        await bot.send_message(
            chat_id,
            text,
            reply_markup=reply_markup,
            reply_parameters=ReplyParameters(message_id=reply_to, allow_sending_without_reply=True),
        )
    except TelegramAPIError:
        logger.exception("Could not send a reply to chat %s", chat_id)


def _render(result: ParseResult, i18n: TranslatorRunner, tz: ZoneInfo) -> str:
    match result.outcome:
        case "parsed":
            return _summary(result, i18n, tz)
        case "not_receipt":
            return i18n.get("receipt-not-a-receipt")
        case "duplicate":
            original = result.duplicate_of or result.card
            return i18n.get(
                "receipt-duplicate",
                store=render.store(original, i18n),
                date=render.date(original, tz),
                amount=render.amount(original, i18n),
            )
        case _:
            return i18n.get("receipt-failed")


def _summary(result: ParseResult, i18n: TranslatorRunner, tz: ZoneInfo) -> str:
    card = result.card
    text = render.header(card, i18n, tz)
    if not result.issues:
        return text
    lines = []
    for issue in result.issues:
        message = escape(issue.message)
        if issue.item_name:
            lines.append(
                i18n.get("receipt-issue-line", item=escape(issue.item_name), message=message)
            )
        else:
            lines.append(i18n.get("receipt-issue-line-plain", message=message))
    if card.open_issue_count > len(result.issues):
        lines.append(i18n.get("receipt-issues-more"))
    header = i18n.get("receipt-issues", count=str(card.open_issue_count))
    return "\n\n".join((text, "\n".join((header, *lines))))


def register_photo(dp) -> None:
    """The photo handler: before the dialogs, so a photo is accepted while a dialog is open
    (a dialog consumes every message sent in its states)."""
    router = Router(name="photo")
    router.message.register(photo_intake, F.photo | F.document)
    dp.include_router(router)


def register_not_a_photo(dp) -> None:
    """The catch-all: after the dialogs, so it never swallows a dialog's text input."""
    router = Router(name="not-a-photo")
    # Any message that is not a command (commands are handled before this router).
    router.message.register(not_a_photo, ~F.text.startswith("/"))
    dp.include_router(router)
