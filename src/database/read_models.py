"""Read models: pydantic shapes for a screen, returned by repository query methods.

They are not aggregates. The services re-export them from `services.results`, so `bot` imports
them from `services` only.
"""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class HistoryRow(BaseModel):
    """One receipt of the month. `day` is in the user's time zone; the amount is empty for a
    receipt that was not read."""

    model_config = ConfigDict(frozen=True)

    receipt_id: int
    day: date
    store_name: str | None
    total: Decimal | None
    currency: str | None
    status: str


class CurrencyTotal(BaseModel):
    model_config = ConfigDict(frozen=True)

    currency: str
    amount: Decimal


class StoreOption(BaseModel):
    model_config = ConfigDict(frozen=True)

    store_id: int
    name: str


class HistoryPage(BaseModel):
    """One page of one month of a user's receipts, with what the header and the buttons need.

    `rows` is the requested page of the month under the store filter, newest first;
    `total_rows` counts all of the month's rows under the filter (for paging). `parsed_count`
    and `totals` (one entry per currency) count parsed receipts only. `stores` are the stores
    with a receipt in the month, whatever the filter. `has_earlier` / `has_later` say whether
    any receipt of the user lies before / after the month, whatever the filter. `store_name` is
    the filter's store, None without a filter or for a store that is not the user's.
    """

    model_config = ConfigDict(frozen=True)

    year: int
    month: int
    rows: list[HistoryRow]
    total_rows: int
    parsed_count: int
    totals: list[CurrencyTotal]
    stores: list[StoreOption]
    has_earlier: bool
    has_later: bool
    store_name: str | None


class ReparseCandidates(BaseModel):
    """The ids of a user's receipts worth reading again, oldest first.

    `failed_ids` are receipts whose last read failed; `outdated_ids` are parsed or not-receipt
    receipts read by a parser other than the current version.
    """

    model_config = ConfigDict(frozen=True)

    failed_ids: list[int]
    outdated_ids: list[int]
