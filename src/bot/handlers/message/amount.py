"""A message that is only an amount starts a manual expense entry.

A dialog takes every message sent while it is open, a card sitting in its resting window
included, so this handler is registered before the dialogs and steps aside itself when the
open window reads typed text (`text_input_states`): a number typed there is that step's input.
A number sent in any other window starts a new entry, replacing the dialog.
"""

import re
from contextlib import ExitStack
from zoneinfo import ZoneInfo

from aiogram import Dispatcher, Router
from aiogram.types import Message
from aiogram_dialog import DialogManager, StartMode

from src.bot.handlers.dialog import no_window_reads_text
from src.bot.handlers.dialog.common import TransferKeys
from src.bot.handlers.dialog.media import keeping_previous_keyboard
from src.bot.handlers.dialog.receipt_card.values import InvalidValue, parse_value
from src.bot.states.expense_entry import ExpenseEntrySG
from src.services.results import CurrentUser

# Up to 8 digits and 2 decimals: the amount of a household expense, and below the column limit.
_AMOUNT = re.compile(r"\d{1,8}([.,]\d{1,2})?", re.ASCII)


def is_amount(text: str) -> bool:
    """True when the whole text is an amount above zero (`12.50`, `12,50`, `7`)."""
    if not _AMOUNT.fullmatch(text):
        return False
    try:
        return parse_value("money", text, ZoneInfo("UTC")) > 0
    except InvalidValue:
        return False


async def is_new_entry(message: Message, **data) -> bool:
    """A bare amount, and no open dialog window that wants typed text."""
    return is_amount(message.text or "") and await no_window_reads_text(**data)


async def start_entry(message: Message, user: CurrentUser, dialog_manager: DialogManager) -> None:
    amount = parse_value("money", message.text or "", ZoneInfo(user.timezone))
    with ExitStack() as stack:
        # A card that is open keeps its buttons: it is a message of its own, not a step of a
        # flow. An older entry's message keeps its text, but its buttons die.
        if dialog_manager.has_context() and (
            dialog_manager.current_context().state.group is not ExpenseEntrySG
        ):
            stack.enter_context(keeping_previous_keyboard())
        await dialog_manager.start(
            ExpenseEntrySG.payee,
            data={TransferKeys.AMOUNT: format(amount, ".2f")},
            mode=StartMode.RESET_STACK,
        )


def register_amount(dp: Dispatcher) -> None:
    router = Router(name="amount")
    router.message.register(start_entry, is_new_entry)
    dp.include_router(router)
