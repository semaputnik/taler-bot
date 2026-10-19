"""What the taps on a card's plain buttons share, for the receipt card and the expense card.

The current card (the last message of the user's dialog) is edited in place; a tap on an older
card sends a fresh one, so the old message keeps its buttons. `Close` hides the buttons and
keeps the text on a card the bot sent by itself; on a card the user asked for (a history row, a
copy of an older card) it deletes the message. A card that is gone alerts and loses its buttons.
"""

import logging
from contextlib import ExitStack

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.state import State
from aiogram.types import CallbackQuery
from aiogram_dialog import DialogManager, ShowMode, StartMode

from src.bot.handlers.dialog.cards import dismissible
from src.bot.handlers.dialog.common import TransferKeys
from src.bot.handlers.dialog.media import keeping_previous_keyboard, tracking_card
from src.bot.handlers.screens import screen_of
from src.bot.screens import ScreenRegistry

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
    screens: ScreenRegistry,
    *,
    state: State | None,
    data: dict,
    dismiss: bool = False,
) -> None:
    """Show `state` of the card's dialog; `state` None means Close: with `dismiss` the card is
    deleted (the user asked for it), otherwise its buttons are hidden and the text stays."""
    await query.answer()
    in_place = (
        query.message is not None
        and dialog_manager.current_stack().last_message_id == query.message.message_id
    )
    if state is None:
        if dismiss:
            await delete_card(bot, query, screens)
        elif not in_place:
            await remove_keyboard(bot, query)
        if in_place:  # the current card's dialog ends with it
            await dialog_manager.reset_stack(remove_keyboard=not dismiss)
        return
    with ExitStack() as stack:
        if not in_place:
            stack.enter_context(keeping_previous_keyboard())  # the older card keeps its buttons
            stack.enter_context(tracking_card())  # a copy the user asked for expires
            data = {**data, TransferKeys.DISMISSIBLE: True}  # ... and its Close deletes it
        elif dialog_manager.has_context() and dismissible(dialog_manager):
            data = {**data, TransferKeys.DISMISSIBLE: True}  # the restarted card stays so
        await dialog_manager.start(
            state,
            data=data,
            mode=StartMode.RESET_STACK,
            show_mode=ShowMode.EDIT if in_place else ShowMode.SEND,
        )


async def delete_card(bot: Bot, query: CallbackQuery, screens: ScreenRegistry) -> None:
    """Delete the card's message (Telegram refuses after 48 hours: then only the buttons go)
    and stop its expiry clock."""
    if query.message is None:
        return
    await screens.forget(screen_of(query.message))
    try:
        await bot.delete_message(chat_id=query.message.chat.id, message_id=query.message.message_id)
    except TelegramBadRequest as error:
        logger.warning("Could not delete card %s: %s", query.message.message_id, error)
        await remove_keyboard(bot, query)


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
