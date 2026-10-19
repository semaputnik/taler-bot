from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Dispatcher
from aiogram.filters import Command
from aiogram.types import Message
from fluentogram import TranslatorRunner

from src.bot.handlers.screens import track_sent
from src.bot.keyboards.stats import StatsAction, StatsCallback, StatsKind
from src.bot.screens import ScreenRegistry
from src.bot.views import stats as view
from src.services.container import Services
from src.services.results import CurrentUser


def current_month(user: CurrentUser, action: StatsAction = StatsAction.SHOW) -> StatsCallback:
    """The stats of the current month in the user's time zone."""
    today = datetime.now(ZoneInfo(user.timezone)).date()
    return StatsCallback.at(StatsKind.MONTH, today, action)


async def send_stats(
    message: Message,
    shown: StatsCallback,
    user: CurrentUser,
    services: Services,
    i18n: TranslatorRunner,
    screens: ScreenRegistry,
) -> None:
    """A new stats message for the period of `shown`."""
    report = await services.expenses.spending(user.id, shown.kind.value, shown.anchor)
    sent = await message.answer(
        view.show_text(report, i18n), reply_markup=view.show_keyboard(report, i18n)
    )
    await track_sent(screens, sent)


async def stats(
    message: Message,
    user: CurrentUser,
    services: Services,
    i18n: TranslatorRunner,
    screens: ScreenRegistry,
) -> None:
    await send_stats(message, current_month(user), user, services, i18n, screens)


def register_stats(dp: Dispatcher) -> None:
    dp.message.register(stats, Command("stats"))
