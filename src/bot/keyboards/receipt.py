"""The inline keyboard under a receipt's summary, and the callback data its buttons carry."""

from enum import StrEnum

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from fluentogram import TranslatorRunner


class CardWindow(StrEnum):
    """The `ReceiptCard` window a summary button opens."""

    MAIN = "main"
    DELETE_CONFIRM = "delete_confirm"


class ReceiptCallback(CallbackData, prefix="receipt"):
    receipt_id: int
    window: CardWindow


def receipt_keyboard(i18n: TranslatorRunner, receipt_id: int) -> InlineKeyboardMarkup:
    """Buttons under the parse reply. Later tickets add Items and Photo next to Delete."""
    delete = ReceiptCallback(receipt_id=receipt_id, window=CardWindow.DELETE_CONFIRM)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=i18n.get("button-delete"), callback_data=delete.pack())]
        ]
    )
