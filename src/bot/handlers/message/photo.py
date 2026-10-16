"""Photo intake: save the photo, answer at once, read it in the background, answer again.

Registered on its own router that `register_handlers` includes after the commands and the
dialogs. aiogram tries a router's own handlers before its sub-routers, so a catch-all on the
dispatcher itself would swallow a dialog's text input; here it comes last.
"""

import logging
from html import escape
from zoneinfo import ZoneInfo

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import Message, ReplyParameters
from aiogram.utils.chat_action import ChatActionSender
from fluentogram import TranslatorRunner

from src.bot.tasks import TaskRegistry
from src.exception import DuplicatePhoto
from src.services.container import Services
from src.services.results import CurrentUser, NewPhoto, ParseResult, ReceiptCard

logger = logging.getLogger(__name__)

MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024  # the Bot API cannot serve bigger files
_DATE_FORMAT = "%d.%m.%Y %H:%M"
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
    try:
        # The sender's worker dies on a failed `sendChatAction` and the block still ends
        # normally, so the typing status never affects the parse or the reply.
        async with ChatActionSender.typing(bot=bot, chat_id=chat_id, interval=TYPING_INTERVAL):
            result = await services.receipts.parse(user_id, receipt_id)
        text = _render(result, i18n, ZoneInfo(tz))
    except Exception:
        # The service has already marked the receipt failed; the user must not wait for nothing.
        logger.exception("Parsing receipt %s failed", receipt_id)
        text = i18n.get("receipt-failed")
    await _send(bot, chat_id, reply_to, text)


async def _send(bot: Bot, chat_id: int, reply_to: int, text: str) -> None:
    """A Telegram failure is logged, never raised into the caller."""
    try:
        await bot.send_message(
            chat_id,
            text,
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
            store, date, amount = (
                _store(original, i18n),
                _date(original, tz),
                _amount(original, i18n),
            )
            return i18n.get("receipt-duplicate", store=store, date=date, amount=amount)
        case _:
            return i18n.get("receipt-failed")


def _summary(result: ParseResult, i18n: TranslatorRunner, tz: ZoneInfo) -> str:
    card = result.card
    store, date, amount = _store(card, i18n), _date(card, tz), _amount(card, i18n)
    payment = _payment(card, i18n)
    text = i18n.get(
        "receipt-summary",
        store=store,
        date=date,
        amount=amount,
        payment=payment,
        items=str(card.item_count),
    )
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


def _store(card: ReceiptCard, i18n: TranslatorRunner) -> str:
    return escape(card.store_name) if card.store_name else i18n.get("receipt-unknown-store")


def _date(card: ReceiptCard, tz: ZoneInfo) -> str:
    return card.purchased_at.astimezone(tz).strftime(_DATE_FORMAT) if card.purchased_at else ""


def _amount(card: ReceiptCard, i18n: TranslatorRunner) -> str:
    if card.total is None:
        return i18n.get("receipt-amount-unknown")
    currency = escape(card.currency or "")
    return i18n.get("receipt-amount", total=format(card.total, ".2f"), currency=currency)


def _payment(card: ReceiptCard, i18n: TranslatorRunner) -> str:
    if card.card_last4:
        if card.card_brand:
            brand = escape(card.card_brand)
            return i18n.get("receipt-payment-card-brand", brand=brand, last4=card.card_last4)
        return i18n.get("receipt-payment-card", last4=card.card_last4)
    if card.payment_method:
        return i18n.get("receipt-payment-method", method=escape(card.payment_method))
    return i18n.get("receipt-payment-none")


def register_photo(dp) -> None:
    router = Router(name="photo")
    router.message.register(photo_intake, F.photo | F.document)
    # Any other message that is not a command (commands are handled before this router).
    router.message.register(not_a_photo, ~F.text.startswith("/"))
    dp.include_router(router)
