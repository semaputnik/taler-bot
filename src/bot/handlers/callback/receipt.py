"""Taps on the buttons under a receipt's summary: open the `ReceiptCard` dialog."""

import logging

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery
from aiogram_dialog import DialogManager, ShowMode, StartMode
from fluentogram import TranslatorRunner

from src.bot.handlers.dialog.common import TransferKeys
from src.bot.keyboards.receipt import CardWindow, ReceiptCallback
from src.bot.states.receipt_card import ReceiptCardSG
from src.exception import ReceiptNotFound
from src.services.container import Services
from src.services.results import CurrentUser

logger = logging.getLogger(__name__)

_WINDOWS = {
    CardWindow.MAIN: ReceiptCardSG.main,
    CardWindow.ITEMS: ReceiptCardSG.items,
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
) -> None:
    try:
        deleted = (await services.receipts.card(user.id, callback_data.receipt_id)).deleted
    except ReceiptNotFound:
        deleted = True
    if deleted:
        await query.answer(i18n.get("card-deleted-alert"), show_alert=True)
        await _remove_keyboard(bot, query)
        return
    await query.answer()
    await dialog_manager.start(
        _WINDOWS[callback_data.window],
        data={TransferKeys.RECEIPT_ID: callback_data.receipt_id},
        mode=StartMode.RESET_STACK,
        show_mode=ShowMode.SEND,  # a new message: the summary is never edited
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
