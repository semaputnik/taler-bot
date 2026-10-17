"""Photo intake: save the photo, answer at once, read it in the background, answer again.

The photo handler is included before the dialogs (a dialog's message handler takes every
message sent while it is open, so a photo would never get through); the catch-all "send me a
photo" is included after them, so it never swallows a dialog's text input.
"""

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message
from aiogram_dialog import DialogManager
from fluentogram import TranslatorRunner

from src.bot.handlers.dialog import no_window_reads_text
from src.bot.handlers.parse_task import read_and_show_card, send_reply
from src.bot.tasks import TaskRegistry
from src.exception import DuplicatePhoto
from src.services.container import Services
from src.services.results import CurrentUser, NewPhoto

MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024  # the Bot API cannot serve bigger files


async def photo_intake(
    message: Message,
    bot: Bot,
    user: CurrentUser,
    services: Services,
    tasks: TaskRegistry,
    i18n: TranslatorRunner,
    dialog_manager: DialogManager,
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

    await send_reply(bot, message.chat.id, message.message_id, i18n.get("receipt-saved"))
    bg = dialog_manager.bg()
    tasks.spawn(
        read_and_show_card(bot, bg, message.chat.id, user.id, card.receipt_id, services),
        name=f"parse-receipt-{card.receipt_id}",
    )


async def not_a_photo(message: Message, i18n: TranslatorRunner) -> None:
    await message.reply(i18n.get("photo-send-me-one"))


def register_photo(dp) -> None:
    """The photo handler: before the dialogs, so a photo is accepted while a dialog is open
    (a dialog consumes every message sent in its states)."""
    router = Router(name="photo")
    router.message.register(photo_intake, F.photo | F.document)
    dp.include_router(router)


def register_not_a_photo(dp) -> None:
    """The catch-all: before the dialogs, so a card resting in its `main` window (or any window
    that does not read text) does not take a stray word and send itself again. It steps aside
    when the open window reads typed text, so the dialog gets that input."""
    router = Router(name="not-a-photo")
    # Any other message, an unknown command included (known commands are handled before this
    # router), so a retired command such as /receipts is answered, not ignored.
    router.message.register(not_a_photo, no_window_reads_text)
    dp.include_router(router)
