"""What the two cards (receipt and expense) have in common on the keyboard side."""

from aiogram.types import InlineKeyboardMarkup

from src.bot.keyboards.expense import ExpenseCallback
from src.bot.keyboards.receipt import ReceiptCallback

_PREFIXES = tuple(
    f"{callback.__prefix__}{callback.__separator__}"
    for callback in (ReceiptCallback, ExpenseCallback)
)


def is_card_markup(markup: object) -> bool:
    """True for a card's resting keyboard: plain `ReceiptCallback` or `ExpenseCallback` buttons,
    which are not tied to a dialog context (see `PlainKeyboardFactory`)."""
    if not isinstance(markup, InlineKeyboardMarkup):
        return False
    return any(
        (button.callback_data or "").startswith(_PREFIXES)
        for row in markup.inline_keyboard
        for button in row
    )
