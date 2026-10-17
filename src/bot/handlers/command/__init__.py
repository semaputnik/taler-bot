from aiogram import Dispatcher

from src.bot.handlers.command.receipts import register_receipts
from src.bot.handlers.command.start import register_start


def register_commands(dp: Dispatcher) -> None:
    register_start(dp)
    register_receipts(dp)
