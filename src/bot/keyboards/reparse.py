"""The callback data of the /reparse message's buttons."""

from typing import Literal

from aiogram.filters.callback_data import CallbackData


class ReparseCallback(CallbackData, prefix="reparse"):
    reason: Literal["failed", "outdated"]
