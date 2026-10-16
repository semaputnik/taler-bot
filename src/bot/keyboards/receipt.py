"""The inline keyboard under a receipt's summary, and the callback data its buttons carry."""

from enum import StrEnum

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from fluentogram import TranslatorRunner


class CardWindow(StrEnum):
    """The `ReceiptCard` window a summary button opens."""

    MAIN = "main"
    ITEMS = "items"
    DELETE_CONFIRM = "delete_confirm"


class ReceiptCallback(CallbackData, prefix="receipt"):
    receipt_id: int
    window: CardWindow


def receipt_keyboard(
    i18n: TranslatorRunner, receipt_id: int, *, item_count: int = 0
) -> InlineKeyboardMarkup:
    """Buttons under the parse reply: Items (only when the receipt has items) and Delete."""
    buttons = []
    if item_count > 0:
        items = ReceiptCallback(receipt_id=receipt_id, window=CardWindow.ITEMS)
        buttons.append(
            InlineKeyboardButton(text=i18n.get("button-items"), callback_data=items.pack())
        )
    delete = ReceiptCallback(receipt_id=receipt_id, window=CardWindow.DELETE_CONFIRM)
    buttons.append(
        InlineKeyboardButton(text=i18n.get("button-delete"), callback_data=delete.pack())
    )
    return InlineKeyboardMarkup(inline_keyboard=[buttons])
