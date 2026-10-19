from aiogram.types import InlineKeyboardMarkup
from aiogram_dialog import DialogManager

from src.bot.handlers.dialog.cards import CardKeyboard, dismissible
from src.bot.handlers.dialog.expense_card.common import DialogDataKeys, PreviewDataKeys
from src.bot.keyboards.expense import expense_keyboard


def _markup(data: dict, manager: DialogManager) -> InlineKeyboardMarkup | None:
    if not data[PreviewDataKeys.CAN_EDIT]:  # a deleted expense has no buttons
        return None
    return expense_keyboard(
        manager.middleware_data["i18n"],
        manager.dialog_data[DialogDataKeys.EXPENSE_ID],
        dismissible=dismissible(manager),
    )


def expense_card_keyboard() -> CardKeyboard:
    """The expense card's resting buttons (`ExpenseCallback`)."""
    return CardKeyboard(_markup)
