from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Dispatcher
from aiogram.filters import Command
from aiogram.types import Message
from fluentogram import TranslatorRunner

from src.bot.keyboards.history import HistoryAction, HistoryCallback
from src.bot.views import history as view
from src.services.container import Services
from src.services.results import CurrentUser


def current_month(user: CurrentUser, action: HistoryAction = HistoryAction.SHOW) -> HistoryCallback:
    """The history of the current month in the user's time zone, all payees, first page."""
    now = datetime.now(ZoneInfo(user.timezone))
    return HistoryCallback(year=now.year, month=now.month, action=action)


async def send_history(
    message: Message,
    shown: HistoryCallback,
    user: CurrentUser,
    services: Services,
    i18n: TranslatorRunner,
) -> None:
    """A new history message for the month `shown` (page 0, payee filter as given)."""
    page = await services.expenses.history(
        user.id, shown.year, shown.month, payee_id=shown.payee_id or None
    )
    await message.answer(
        view.show_text(page, i18n), reply_markup=view.show_keyboard(page, shown, i18n)
    )


async def expenses(
    message: Message, user: CurrentUser, services: Services, i18n: TranslatorRunner
) -> None:
    await send_history(message, current_month(user), user, services, i18n)


def register_expenses(dp: Dispatcher) -> None:
    dp.message.register(expenses, Command("expenses"))
