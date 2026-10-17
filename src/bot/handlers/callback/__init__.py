from aiogram import Dispatcher

from src.bot.handlers.callback.history import register_history_callbacks
from src.bot.handlers.callback.receipt import register_receipt_callbacks
from src.bot.handlers.callback.reparse import register_reparse_callbacks
from src.bot.handlers.callback.stats import register_stats_callbacks


def register_callbacks(dp: Dispatcher) -> None:
    register_receipt_callbacks(dp)
    register_history_callbacks(dp)
    register_reparse_callbacks(dp)
    register_stats_callbacks(dp)
