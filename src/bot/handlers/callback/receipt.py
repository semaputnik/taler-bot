"""Taps on the plain buttons of a receipt card: show the `ReceiptCard` dialog window."""

import logging
from contextlib import ExitStack

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery
from aiogram_dialog import DialogManager, ShowMode, StartMode
from fluentogram import TranslatorRunner

from src.bot.handlers.dialog.common import TransferKeys
from src.bot.handlers.dialog.media import keeping_previous_keyboard
from src.bot.handlers.parse_task import read_and_show_card, send_reply
from src.bot.keyboards.receipt import CardWindow, ReceiptCallback
from src.bot.states.receipt_card import ReceiptCardSG
from src.bot.tasks import TaskRegistry
from src.exception import ReceiptNotFound
from src.services.container import Services
from src.services.results import CurrentUser, ReceiptCard

logger = logging.getLogger(__name__)

_WINDOWS = {
    CardWindow.MAIN: ReceiptCardSG.main,
    CardWindow.ITEMS: ReceiptCardSG.items,
    CardWindow.REVIEW: ReceiptCardSG.issue,
    CardWindow.PHOTO: ReceiptCardSG.photo,
    CardWindow.DELETE_CONFIRM: ReceiptCardSG.delete_confirm,
}
_GONE_MARKERS = ("message to edit not found", "message is not modified")


async def open_card(
    query: CallbackQuery,
    callback_data: ReceiptCallback,
    dialog_manager: DialogManager,
    user: CurrentUser,
    services: Services,
    i18n: TranslatorRunner,
    bot: Bot,
    tasks: TaskRegistry,
) -> None:
    try:
        card = await services.receipts.card(user.id, callback_data.receipt_id)
        deleted = card.deleted
    except ReceiptNotFound:
        card, deleted = None, True
    if deleted:
        await query.answer(i18n.get("card-deleted-alert"), show_alert=True)
        await _remove_keyboard(bot, query)
        return
    if callback_data.window is CardWindow.REPARSE:
        await _reparse(query, callback_data, dialog_manager, user, services, i18n, bot, tasks, card)
        return
    await query.answer()
    in_place = (
        query.message is not None
        and dialog_manager.current_stack().last_message_id == query.message.message_id
    )
    if callback_data.window is CardWindow.CLOSE:
        # Hide the card's buttons; the text stays. The current card's dialog ends with it.
        if in_place:
            await dialog_manager.reset_stack(remove_keyboard=True)
        else:
            await _remove_keyboard(bot, query)
        return
    # The current card is edited in place; a tap on an older one sends a fresh card, so the
    # old message keeps its buttons.
    with ExitStack() as stack:
        if not in_place:
            stack.enter_context(keeping_previous_keyboard())  # the older card keeps its buttons
        await dialog_manager.start(
            _WINDOWS[callback_data.window],
            data={TransferKeys.RECEIPT_ID: callback_data.receipt_id},
            mode=StartMode.RESET_STACK,
            show_mode=ShowMode.EDIT if in_place else ShowMode.SEND,
        )


async def _reparse(
    query: CallbackQuery,
    callback_data: ReceiptCallback,
    dialog_manager: DialogManager,
    user: CurrentUser,
    services: Services,
    i18n: TranslatorRunner,
    bot: Bot,
    tasks: TaskRegistry,
    card: ReceiptCard,
) -> None:
    """Read the receipt again in the background. The old card keeps its buttons; the new
    reading arrives as a fresh card."""
    if not card.can_reparse or query.message is None:
        await query.answer(i18n.get("reparse-not-possible"), show_alert=True)
        return
    await query.answer()
    chat_id, card_message_id = query.message.chat.id, query.message.message_id
    await send_reply(bot, chat_id, card_message_id, i18n.get("reparse-started"))
    tasks.spawn(
        read_and_show_card(
            bot, dialog_manager.bg(), chat_id, user.id, callback_data.receipt_id, services
        ),
        name=f"reparse-receipt-{callback_data.receipt_id}",
    )


async def _remove_keyboard(bot: Bot, query: CallbackQuery) -> None:
    if query.message is None:
        return
    try:
        await bot.edit_message_reply_markup(
            chat_id=query.message.chat.id, message_id=query.message.message_id, reply_markup=None
        )
    except TelegramBadRequest as error:
        if not any(marker in str(error) for marker in _GONE_MARKERS):
            raise


def register_receipt_callbacks(dp: Dispatcher) -> None:
    dp.callback_query.register(open_card, ReceiptCallback.filter())
