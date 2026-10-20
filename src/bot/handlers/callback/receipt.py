"""Taps on the plain buttons of a receipt card: show the `ReceiptCard` dialog window."""

from aiogram import Bot, Dispatcher
from aiogram.types import CallbackQuery
from aiogram_dialog import DialogManager
from fluentogram import TranslatorRunner

from src.bot.handlers.callback.cards import alert_gone, open_window
from src.bot.handlers.dialog.common import TransferKeys
from src.bot.keyboards.receipt import CardWindow, ReceiptCallback
from src.bot.screens import ScreenRegistry
from src.bot.states.receipt_card import ReceiptCardSG
from src.exception import ReceiptNotFound
from src.services.container import Services
from src.services.results import CurrentUser

_WINDOWS = {
    CardWindow.MAIN: ReceiptCardSG.main,
    CardWindow.ITEMS: ReceiptCardSG.items,
    CardWindow.REVIEW: ReceiptCardSG.issue,
    CardWindow.CATEGORY: ReceiptCardSG.category,
    CardWindow.TAGS: ReceiptCardSG.tags,
    CardWindow.PHOTO: ReceiptCardSG.photo,
    CardWindow.DELETE_CONFIRM: ReceiptCardSG.delete_confirm,
    CardWindow.EDIT: ReceiptCardSG.edit,
    CardWindow.REPARSE: ReceiptCardSG.reparse_confirm,
}  # CardWindow.CLOSE and CardWindow.DISMISS are not windows


async def open_card(
    query: CallbackQuery,
    callback_data: ReceiptCallback,
    dialog_manager: DialogManager,
    user: CurrentUser,
    services: Services,
    i18n: TranslatorRunner,
    bot: Bot,
    screens: ScreenRegistry,
) -> None:
    try:
        card = await services.receipts.card(user.id, callback_data.receipt_id)
        deleted = card.deleted
    except ReceiptNotFound:
        card, deleted = None, True
    if deleted:
        await alert_gone(query, bot, i18n.get("card-deleted-alert"))
        return
    if callback_data.window is CardWindow.REPARSE and not card.can_reparse:
        await query.answer(i18n.get("reparse-not-possible"), show_alert=True)
        return
    if callback_data.window is CardWindow.EDIT and not card.can_edit:
        await query.answer(i18n.get("edit-not-possible"), show_alert=True)
        return
    if callback_data.window is CardWindow.CATEGORY and card.expense_id is None:
        await query.answer(i18n.get("category-not-possible"), show_alert=True)
        return
    if callback_data.window is CardWindow.TAGS and card.expense_id is None:
        await query.answer(i18n.get("tags-not-possible"), show_alert=True)
        return
    await open_window(
        query,
        dialog_manager,
        bot,
        screens,
        state=_WINDOWS.get(callback_data.window),  # Close and Dismiss have no window
        data={TransferKeys.RECEIPT_ID: callback_data.receipt_id},
        dismiss=callback_data.window is CardWindow.DISMISS,
    )


def register_receipt_callbacks(dp: Dispatcher) -> None:
    dp.callback_query.register(open_card, ReceiptCallback.filter())
