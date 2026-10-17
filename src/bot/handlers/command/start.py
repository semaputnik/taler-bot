from html import escape

from aiogram import Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from fluentogram import TranslatorRunner

from src.bot.handlers.command import receipts as history_command
from src.bot.handlers.command import stats as stats_command
from src.bot.keyboards.history import HistoryAction
from src.bot.keyboards.stats import StatsAction
from src.services.results import CurrentUser


async def start(message: Message, user: CurrentUser, i18n: TranslatorRunner) -> None:
    # The bot uses HTML parse mode, so the name must be escaped.
    receipts = InlineKeyboardButton(
        text=i18n.get("button-receipts"),
        callback_data=history_command.current_month(user, HistoryAction.OPEN).pack(),
    )
    spending = InlineKeyboardButton(
        text=i18n.get("button-spending"),
        callback_data=stats_command.current_month(user, StatsAction.OPEN).pack(),
    )
    await message.answer(
        i18n.start.greeting(first_name=escape(user.first_name or "")),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[receipts, spending]]),
    )


def register_start(dp: Dispatcher) -> None:
    dp.message.register(start, CommandStart())
