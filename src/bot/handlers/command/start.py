from html import escape

from aiogram import Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from fluentogram import TranslatorRunner

from src.bot.handlers.command.receipts import current_month
from src.bot.keyboards.history import HistoryAction
from src.services.results import CurrentUser


async def start(message: Message, user: CurrentUser, i18n: TranslatorRunner) -> None:
    # The bot uses HTML parse mode, so the name must be escaped.
    receipts = InlineKeyboardButton(
        text=i18n.get("button-receipts"),
        callback_data=current_month(user, HistoryAction.OPEN).pack(),
    )
    await message.answer(
        i18n.start.greeting(first_name=escape(user.first_name or "")),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[receipts]]),
    )


def register_start(dp: Dispatcher) -> None:
    dp.message.register(start, CommandStart())
