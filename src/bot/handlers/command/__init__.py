from aiogram import Dispatcher

from src.bot.handlers.command.expenses import register_expenses
from src.bot.handlers.command.reparse import register_reparse
from src.bot.handlers.command.start import register_start
from src.bot.handlers.command.stats import register_stats


def register_commands(dp: Dispatcher) -> None:
    register_start(dp)
    register_expenses(dp)
    register_reparse(dp)
    register_stats(dp)
