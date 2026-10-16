from html import escape

from aiogram import Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import Message
from fluentogram import TranslatorRunner

from src.usecases.user.ensure_user import CurrentUser


async def start(message: Message, user: CurrentUser, i18n: TranslatorRunner) -> None:
    # The bot uses HTML parse mode, so the name must be escaped.
    await message.answer(i18n.start.greeting(first_name=escape(user.first_name or "")))


def register_start(dp: Dispatcher) -> None:
    dp.message.register(start, CommandStart())
