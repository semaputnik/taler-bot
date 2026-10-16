from html import escape
from zoneinfo import ZoneInfo

from aiogram_dialog import DialogManager
from fluentogram import TranslatorRunner

from src.bot import render
from src.bot.handlers.dialog.media import StoredPhoto
from src.bot.handlers.dialog.receipt_card.common import DialogDataKeys, PreviewDataKeys
from src.bot.handlers.dialog.receipt_card.model import (
    ItemChoice,
    ItemPreview,
    ItemsPreview,
    MainPreview,
)
from src.services.container import Services
from src.services.results import CurrentUser, ItemRow, ReceiptCard

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
        text=_text(card, i18n, ZoneInfo(user.timezone)),
        can_delete=not card.deleted,
        has_items=card.status == "parsed" and card.item_count > 0 and not card.deleted,
    ).to_data()


async def items_getter(
    dialog_manager: DialogManager,
    services: Services,
    user: CurrentUser,
    i18n: TranslatorRunner,
    **_,
) -> dict:
    rows = await services.receipts.items(
        user.id, dialog_manager.dialog_data[DialogDataKeys.RECEIPT_ID]
    )
    return ItemsPreview(
        text=i18n.get("card-items-title", count=str(len(rows))),
        items=[ItemChoice(id=str(i), text=_row_text(row, i18n)) for i, row in enumerate(rows)],
    ).to_data()


async def item_getter(
    dialog_manager: DialogManager,
    services: Services,
    user: CurrentUser,
    i18n: TranslatorRunner,
    **_,
) -> dict:
    # One service call; the selected item is picked from the result.
    rows = await services.receipts.items(
        user.id, dialog_manager.dialog_data[DialogDataKeys.RECEIPT_ID]
    )
    ref = dialog_manager.dialog_data.get(DialogDataKeys.ITEM_REF)
    row = next((r for r in rows if r.ref == ref), None)
    text = _item_text(row, i18n) if row is not None else i18n.get("item-gone")
    return ItemPreview(text=text).to_data()


def _row_text(row: ItemRow, i18n: TranslatorRunner) -> str:
    return i18n.get(
        "item-row",
        name=row.readable_name,
        quantity=render.quantity(row.quantity),
        unit=row.unit,
        total=render.money(row.line_total, i18n),
    )


def _item_text(row: ItemRow, i18n: TranslatorRunner) -> str:
    lines = [
        i18n.get("item-title", name=escape(row.readable_name)),
        i18n.get("item-printed", name=escape(row.printed_name)),
        i18n.get("item-category", category=i18n.get(f"category-{row.category.replace('_', '-')}")),
        i18n.get("item-quantity", quantity=render.quantity(row.quantity), unit=escape(row.unit)),
        i18n.get("item-unit-price", price=render.money(row.unit_price, i18n)),
        i18n.get(
            "item-reference-price",
            price=render.money(row.reference_price, i18n),
            unit=escape(row.reference_unit) if row.reference_unit else "",
        )
        if row.reference_price is not None
        else None,
        i18n.get("item-discount", amount=render.money(row.discount, i18n))
        if row.discount
        else None,
        i18n.get("item-line-total", amount=render.money(row.line_total, i18n)),
        i18n.get("item-vat", rate=render.quantity(row.vat_rate))
        if row.vat_rate is not None
        else None,
    ]
    return "\n".join(line for line in lines if line is not None)


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
