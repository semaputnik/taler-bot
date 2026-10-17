"""The callback data of the history message's buttons. Each button carries the whole view state,
so the message keeps working however old it is."""

from enum import StrEnum

from aiogram.filters.callback_data import CallbackData


class HistoryAction(StrEnum):
    OPEN = "open"  # the /start button: send the month as a new message
    SHOW = "show"  # the month's expenses, edited in place
    PAYEES = "payees"  # the payee chooser


class HistoryCallback(CallbackData, prefix="history"):
    year: int
    month: int
    payee_id: int = 0  # 0 = all payees
    page: int = 0
    action: HistoryAction = HistoryAction.SHOW
