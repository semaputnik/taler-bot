from zoneinfo import ZoneInfo

from aiogram_dialog import DialogManager
from fluentogram import TranslatorRunner

from src.bot import render
from src.bot.handlers.dialog.media import StoredPhoto
from src.bot.handlers.dialog.receipt_card.common import DialogDataKeys, PreviewDataKeys
from src.bot.handlers.dialog.receipt_card.model import MainPreview
from src.services.container import Services
from src.services.results import CurrentUser, ReceiptCard

_STATUS_KEYS = {
    "pending": "card-status-pending",
    "parsing": "card-status-parsing",
    "failed": "card-status-failed",
    "not_receipt": "card-status-not-receipt",
    "duplicate": "card-status-duplicate",
}


async def main_getter(
    dialog_manager: DialogManager,
    services: Services,
    user: CurrentUser,
    i18n: TranslatorRunner,
    **_,
) -> dict:
    card = await services.receipts.card(
        user.id, dialog_manager.dialog_data[DialogDataKeys.RECEIPT_ID]
    )
    return MainPreview(
        text=_text(card, i18n, ZoneInfo(user.timezone)), can_delete=not card.deleted
    ).to_data()


async def photo_getter(
    dialog_manager: DialogManager,
    services: Services,
    user: CurrentUser,
    i18n: TranslatorRunner,
    **_,
) -> dict:
    """The photo by its Telegram file id. The bytes are loaded only if Telegram refuses it."""
    receipt_id = dialog_manager.dialog_data[DialogDataKeys.RECEIPT_ID]
    ref = await services.receipts.photo(user.id, receipt_id)
    return {
        PreviewDataKeys.PHOTO: StoredPhoto(
            ref.telegram_file_id,
            lambda: services.receipts.photo_bytes(user.id, receipt_id),
            i18n.get("card-photo-unavailable"),
        )
    }


def _text(card: ReceiptCard, i18n: TranslatorRunner, tz: ZoneInfo) -> str:
    if card.deleted:
        return i18n.get("card-deleted")
    if card.status == "parsed":
        return render.header(card, i18n, tz)
    lines = [i18n.get(_STATUS_KEYS[card.status])]
    lines.append(
        i18n.get("card-received", date=card.received_at.astimezone(tz).strftime(render.DATE_FORMAT))
    )
    if card.duplicate_of is not None:
        original = card.duplicate_of
        lines.append(
            i18n.get(
                "card-repeats",
                store=render.store(original, i18n),
                date=render.date(original, tz),
                amount=render.amount(original, i18n),
            )
        )
    return "\n".join(lines)
