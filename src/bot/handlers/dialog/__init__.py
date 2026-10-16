from aiogram import Dispatcher

from src.bot.handlers.dialog.receipt_card.dialog import create_receipt_card_dialog


def register_dialogs(dp: Dispatcher) -> None:
    dp.include_router(create_receipt_card_dialog())
