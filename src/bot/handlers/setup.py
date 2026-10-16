from aiogram import Dispatcher

from src.bot.handlers.command import register_commands
from src.bot.handlers.dialog import register_dialogs
from src.bot.handlers.message.photo import register_photo


def register_handlers(dp: Dispatcher) -> None:
    # Order matters: the photo router holds a catch-all, so it comes last.
    register_commands(dp)
    register_dialogs(dp)
    register_photo(dp)
