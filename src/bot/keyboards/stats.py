"""The callback data of the stats message's buttons. Each button carries the whole view state (the
kind and an anchor date inside the period), so the message keeps working however old it is."""

from datetime import date
from enum import StrEnum

from aiogram.filters.callback_data import CallbackData


class StatsKind(StrEnum):
    WEEK = "week"
    MONTH = "month"


class StatsAction(StrEnum):
    OPEN = "open"  # the /start button: send the period as a new message
    SHOW = "show"  # the period, edited in place


class StatsCallback(CallbackData, prefix="stats"):
    kind: StatsKind
    year: int
    month: int
    day: int
    action: StatsAction = StatsAction.SHOW

    @classmethod
    def at(
        cls, kind: StatsKind, anchor: date, action: StatsAction = StatsAction.SHOW
    ) -> StatsCallback:
        return cls(kind=kind, year=anchor.year, month=anchor.month, day=anchor.day, action=action)

    @property
    def anchor(self) -> date:
        return date(self.year, self.month, self.day)
