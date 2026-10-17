from aiogram import Dispatcher

from src.bot.handlers.callback.receipt import register_receipt_callbacks


def register_callbacks(dp: Dispatcher) -> None:
    register_receipt_callbacks(dp)
