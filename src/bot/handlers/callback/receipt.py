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
from src.bot.keyboards.receipt import CardWindow, ReceiptCallback
from src.bot.states.receipt_card import ReceiptCardSG
from src.exception import ReceiptNotFound
from src.services.container import Services
from src.services.results import CurrentUser

logger = logging.getLogger(__name__)

_WINDOWS = {
    CardWindow.MAIN: ReceiptCardSG.main,
    CardWindow.ITEMS: ReceiptCardSG.items,
    CardWindow.REVIEW: ReceiptCardSG.issue,
    CardWindow.PHOTO: ReceiptCardSG.photo,
    CardWindow.DELETE_CONFIRM: ReceiptCardSG.delete_confirm,
    CardWindow.REPARSE: ReceiptCardSG.reparse_confirm,
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
    if callback_data.window is CardWindow.REPARSE and not card.can_reparse:
        await query.answer(i18n.get("reparse-not-possible"), show_alert=True)
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
