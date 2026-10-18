"""What the taps on a card's plain buttons share, for the receipt card and the expense card.

The current card (the last message of the user's dialog) is edited in place; a tap on an older
card sends a fresh one, so the old message keeps its buttons. `Close` hides the buttons and
keeps the text. A card that is gone alerts and loses its buttons.
"""

import logging
from contextlib import ExitStack

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.state import State
from aiogram.types import CallbackQuery
from aiogram_dialog import DialogManager, ShowMode, StartMode

from src.bot.handlers.dialog.media import keeping_previous_keyboard

logger = logging.getLogger(__name__)

_GONE_MARKERS = ("message to edit not found", "message is not modified")


async def alert_gone(query: CallbackQuery, bot: Bot, text: str) -> None:
    """The card was deleted (or never existed): say so and take its buttons away."""
    await query.answer(text, show_alert=True)
    await remove_keyboard(bot, query)


async def open_window(
    query: CallbackQuery,
    dialog_manager: DialogManager,
    bot: Bot,
    *,
    state: State | None,
    data: dict,
) -> None:
    """Show `state` of the card's dialog; `state` None means Close."""
    await query.answer()
    in_place = (
        query.message is not None
        and dialog_manager.current_stack().last_message_id == query.message.message_id
    )
    if state is None:
        # Hide the card's buttons; the text stays. The current card's dialog ends with it.
        if in_place:
            await dialog_manager.reset_stack(remove_keyboard=True)
        else:
            await remove_keyboard(bot, query)
        return
    with ExitStack() as stack:
        if not in_place:
            stack.enter_context(keeping_previous_keyboard())  # the older card keeps its buttons
        await dialog_manager.start(
            state,
            data=data,
            mode=StartMode.RESET_STACK,
            show_mode=ShowMode.EDIT if in_place else ShowMode.SEND,
        )


async def remove_keyboard(bot: Bot, query: CallbackQuery) -> None:
    if query.message is None:
        return
    try:
        await bot.edit_message_reply_markup(
            chat_id=query.message.chat.id, message_id=query.message.message_id, reply_markup=None
        )
    except TelegramBadRequest as error:
        if not any(marker in str(error) for marker in _GONE_MARKERS):
            raise
