from aiogram import Dispatcher

from src.bot.handlers.callback import register_callbacks
from src.bot.handlers.command import register_commands
from src.bot.handlers.dialog import register_dialogs
from src.bot.handlers.message.amount import register_amount
from src.bot.handlers.message.photo import register_not_a_photo, register_photo


def register_handlers(dp: Dispatcher) -> None:
    # Order matters. A dialog takes every message sent while it is open, a card resting in its
    # `main` window included, so everything that must see a message first comes before the
    # dialogs: photos, bare numbers (which start a manual entry) and the "send me a photo"
    # catch-all. The last two step aside themselves when the open window reads typed text, so
    # that text reaches the dialog.
    register_commands(dp)
    register_callbacks(dp)
    register_photo(dp)
    register_amount(dp)
    register_not_a_photo(dp)
    register_dialogs(dp)
