"""Taps on the plain buttons of an expense card: show the `ExpenseCard` dialog window."""

from aiogram import Bot, Dispatcher
from aiogram.types import CallbackQuery
from aiogram_dialog import DialogManager
from fluentogram import TranslatorRunner

from src.bot.handlers.callback.cards import alert_gone, open_window
from src.bot.handlers.dialog.common import TransferKeys
from src.bot.keyboards.expense import ExpenseCallback, ExpenseWindow
from src.bot.screens import ScreenRegistry
from src.bot.states.expense_card import ExpenseCardSG
from src.exception import ExpenseNotFound
from src.services.container import Services
from src.services.results import CurrentUser

_WINDOWS = {
    ExpenseWindow.MAIN: ExpenseCardSG.main,
    ExpenseWindow.AMOUNT: ExpenseCardSG.amount,
    ExpenseWindow.PAYEE: ExpenseCardSG.payee,
    ExpenseWindow.SOURCE: ExpenseCardSG.source,
    ExpenseWindow.CATEGORY: ExpenseCardSG.category,
    ExpenseWindow.DATE: ExpenseCardSG.date,
    ExpenseWindow.TAGS: ExpenseCardSG.tags,
    ExpenseWindow.DELETE_CONFIRM: ExpenseCardSG.delete_confirm,
}  # ExpenseWindow.CLOSE and ExpenseWindow.DISMISS are not windows


async def open_expense_card(
    query: CallbackQuery,
    callback_data: ExpenseCallback,
    dialog_manager: DialogManager,
    user: CurrentUser,
    services: Services,
    i18n: TranslatorRunner,
    bot: Bot,
    screens: ScreenRegistry,
) -> None:
    try:
        card = await services.expenses.card(user.id, callback_data.expense_id)
        deleted = card.deleted
    except ExpenseNotFound:
        deleted = True
    if deleted:
        await alert_gone(query, bot, i18n.get("expense-deleted-alert"))
        return
    await open_window(
        query,
        dialog_manager,
        bot,
        screens,
        state=_WINDOWS.get(callback_data.window),  # Close and Dismiss have no window
        data={TransferKeys.EXPENSE_ID: callback_data.expense_id},
        dismiss=callback_data.window is ExpenseWindow.DISMISS,
    )


def register_expense_callbacks(dp: Dispatcher) -> None:
    dp.callback_query.register(open_expense_card, ExpenseCallback.filter())
