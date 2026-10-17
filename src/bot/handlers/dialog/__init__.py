from functools import cache

from aiogram import Dispatcher
from aiogram.fsm.state import State
from aiogram_dialog import Dialog

from src.bot.handlers.dialog.expense_entry.dialog import create_expense_entry_dialog
from src.bot.handlers.dialog.receipt_card.dialog import create_receipt_card_dialog


def _create_dialogs() -> list[Dialog]:
    return [create_receipt_card_dialog(), create_expense_entry_dialog()]


def register_dialogs(dp: Dispatcher) -> None:
    for dialog in _create_dialogs():
        dp.include_router(dialog)


@cache
def text_input_states() -> frozenset[State]:
    """The states whose window reads typed text. A message sent in one of them is that step's
    input, so nothing else (a bare number starting an entry) may take it."""
    return frozenset(
        state
        for dialog in _create_dialogs()
        for state, window in dialog.windows.items()
        if getattr(window, "on_message", None) is not None
    )
