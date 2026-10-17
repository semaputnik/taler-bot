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
    """The history of the current month in the user's time zone, all stores, first page."""
    now = datetime.now(ZoneInfo(user.timezone))
    return HistoryCallback(year=now.year, month=now.month, action=action)


async def send_history(
    message: Message,
    shown: HistoryCallback,
    user: CurrentUser,
    services: Services,
    i18n: TranslatorRunner,
) -> None:
    """A new history message for the month `shown` (page 0, store filter as given)."""
    page = await services.receipts.history(
        user.id, shown.year, shown.month, store_id=shown.store_id or None
    )
    await message.answer(
        view.show_text(page, i18n), reply_markup=view.show_keyboard(page, shown, i18n)
    )


async def receipts(
    message: Message, user: CurrentUser, services: Services, i18n: TranslatorRunner
) -> None:
    await send_history(message, current_month(user), user, services, i18n)


def register_receipts(dp: Dispatcher) -> None:
    dp.message.register(receipts, Command("receipts"))
