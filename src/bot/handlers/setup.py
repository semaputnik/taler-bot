from aiogram import Dispatcher

from src.bot.handlers.callback import register_callbacks
from src.bot.handlers.command import register_commands
from src.bot.handlers.dialog import register_dialogs
from src.bot.handlers.message.amount import register_amount
from src.bot.handlers.message.photo import register_not_a_photo, register_photo


def register_handlers(dp: Dispatcher) -> None:
    # Order matters. A dialog takes every message sent while it is open, so photos and bare
    # numbers (which start a manual entry, unless the open window reads typed text) are handled
    # before the dialogs; the catch-all would swallow a dialog's text input, so it comes last.
    register_commands(dp)
    register_callbacks(dp)
    register_photo(dp)
    register_amount(dp)
    register_dialogs(dp)
    register_not_a_photo(dp)
