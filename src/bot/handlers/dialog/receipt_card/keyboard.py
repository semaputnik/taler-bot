from aiogram.types import InlineKeyboardMarkup
from aiogram_dialog import DialogManager

from src.bot.handlers.dialog.cards import CardKeyboard, dismissible
from src.bot.handlers.dialog.receipt_card.common import DialogDataKeys, PreviewDataKeys
from src.bot.keyboards.receipt import receipt_keyboard


def _markup(data: dict, manager: DialogManager) -> InlineKeyboardMarkup | None:
    if not data[PreviewDataKeys.CAN_DELETE]:  # a deleted card has no buttons
        return None
    return receipt_keyboard(
        manager.middleware_data["i18n"],
        manager.dialog_data[DialogDataKeys.RECEIPT_ID],
        item_count=1 if data[PreviewDataKeys.HAS_ITEMS] else 0,
        review_count=data[PreviewDataKeys.REVIEW_COUNT],
        can_reparse=data[PreviewDataKeys.CAN_REPARSE],
        can_categorise=data[PreviewDataKeys.HAS_EXPENSE],
        dismissible=dismissible(manager),
    )


def receipt_card_keyboard() -> CardKeyboard:
    """The receipt card's resting buttons (`ReceiptCallback`)."""
    return CardKeyboard(_markup)
