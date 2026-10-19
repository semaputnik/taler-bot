"""The inline keyboard under an expense typed by hand, and the callback data its buttons carry."""

from enum import StrEnum

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from fluentogram import TranslatorRunner


class ExpenseWindow(StrEnum):
    """The `ExpenseCard` window a button opens."""

    MAIN = "main"
    AMOUNT = "amount"
    PAYEE = "payee"
    SOURCE = "source"
    CATEGORY = "category"
    DATE = "date"
    TAGS = "tags"
    DELETE_CONFIRM = "delete_confirm"
    CLOSE = "close"  # not a window: hides the card's buttons
    DISMISS = "dismiss"  # not a window: deletes the card (one the user opened from a list)


class ExpenseCallback(CallbackData, prefix="expense"):
    expense_id: int
    window: ExpenseWindow


_BUTTON_KEYS = {
    ExpenseWindow.AMOUNT: "button-amount",
    ExpenseWindow.PAYEE: "button-payee",
    ExpenseWindow.SOURCE: "button-source",
    ExpenseWindow.CATEGORY: "button-category",
    ExpenseWindow.DATE: "button-date",
    ExpenseWindow.TAGS: "button-tags",
    ExpenseWindow.DELETE_CONFIRM: "button-delete",
    ExpenseWindow.CLOSE: "button-close",
    ExpenseWindow.DISMISS: "button-close",
}

# Two buttons per row; Delete and Close each on their own row.
_LAYOUT = (
    (ExpenseWindow.AMOUNT, ExpenseWindow.PAYEE),
    (ExpenseWindow.SOURCE, ExpenseWindow.CATEGORY),
    (ExpenseWindow.DATE, ExpenseWindow.TAGS),
    (ExpenseWindow.DELETE_CONFIRM,),
    (ExpenseWindow.CLOSE,),
)


def expense_keyboard(
    i18n: TranslatorRunner, expense_id: int, *, dismissible: bool = False
) -> InlineKeyboardMarkup:
    """Buttons under an expense card: Amount, Payee / Source, Category / Date, Tags / Delete /
    Close (which deletes a card the user opened from a list, `dismissible`)."""

    def button(window: ExpenseWindow) -> InlineKeyboardButton:
        return InlineKeyboardButton(
            text=i18n.get(_BUTTON_KEYS[window]),
            callback_data=ExpenseCallback(expense_id=expense_id, window=window).pack(),
        )

    close = ExpenseWindow.DISMISS if dismissible else ExpenseWindow.CLOSE
    rows = [
        [button(close if window is ExpenseWindow.CLOSE else window) for window in row]
        for row in _LAYOUT
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)
