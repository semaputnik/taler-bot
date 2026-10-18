from functools import cache

from aiogram import Dispatcher
from aiogram.fsm.state import State
from aiogram_dialog import Dialog
from aiogram_dialog.api.entities import Context
from aiogram_dialog.api.internal import CONTEXT_KEY

from src.bot.handlers.dialog.expense_card.dialog import create_expense_card_dialog
from src.bot.handlers.dialog.expense_entry.dialog import create_expense_entry_dialog
from src.bot.handlers.dialog.receipt_card.dialog import create_receipt_card_dialog


def _create_dialogs() -> list[Dialog]:
    return [
        create_receipt_card_dialog(),
        create_expense_card_dialog(),
        create_expense_entry_dialog(),
    ]


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


async def no_window_reads_text(*_, **data) -> bool:
    """True when no dialog window that reads typed text is open. The dialogs' own middleware
    puts the open context (the window on screen) into the handler data. Handlers that take free
    text (a bare number, the "send me a photo" catch-all) step aside when this is false, so the
    text reaches the window instead. It works as an aiogram filter (the event comes first)."""
    context: Context | None = data.get(CONTEXT_KEY)
    return context is None or context.state not in text_input_states()
