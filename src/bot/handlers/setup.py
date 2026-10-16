from aiogram import Dispatcher

from src.bot.handlers.command import register_commands
from src.bot.handlers.dialog import register_dialogs


def register_handlers(dp: Dispatcher) -> None:
    register_commands(dp)
    register_dialogs(dp)
