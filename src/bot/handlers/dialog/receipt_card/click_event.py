from aiogram.types import CallbackQuery
from aiogram_dialog import DialogManager
from aiogram_dialog.widgets.kbd import Button
from fluentogram import TranslatorRunner

from src.bot.handlers.dialog.receipt_card.common import DialogDataKeys
from src.bot.states.receipt_card import ReceiptCardSG
from src.exception import InvalidReceiptTransition, ReceiptNotFound
from src.services.container import Services
from src.services.results import CurrentUser


async def ask_delete(query: CallbackQuery, button: Button, manager: DialogManager) -> None:
    await manager.switch_to(ReceiptCardSG.delete_confirm)


async def back_to_main(query: CallbackQuery, button: Button, manager: DialogManager) -> None:
    await manager.switch_to(ReceiptCardSG.main)


async def close(query: CallbackQuery, button: Button, manager: DialogManager) -> None:
    await manager.done()


async def confirm_delete(query: CallbackQuery, button: Button, manager: DialogManager) -> None:
    services: Services = manager.middleware_data["services"]
    user: CurrentUser = manager.middleware_data["user"]
    i18n: TranslatorRunner = manager.middleware_data["i18n"]
    receipt_id = manager.dialog_data[DialogDataKeys.RECEIPT_ID]
    try:
        await services.receipts.soft_delete(user.id, receipt_id)
    except InvalidReceiptTransition:
        # Either the receipt is still being read, or it was deleted meanwhile.
        if await _is_deleted(services, user.id, receipt_id):
            await query.answer(i18n.get("card-deleted-alert"), show_alert=True)
            await manager.done()
        else:
            await query.answer(i18n.get("card-cannot-delete-parsing"), show_alert=True)
            await manager.switch_to(ReceiptCardSG.main)
        return
    except ReceiptNotFound:
        await query.answer(i18n.get("card-deleted-alert"), show_alert=True)
        await manager.done()
        return
    await query.answer()
    await manager.done()
    if query.message is not None:
        await query.message.answer(i18n.get("card-deleted-done"))


async def _is_deleted(services: Services, user_id: int, receipt_id: int) -> bool:
    try:
        return (await services.receipts.card(user_id, receipt_id)).deleted
    except ReceiptNotFound:
        return True
