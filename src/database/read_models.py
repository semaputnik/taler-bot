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


class Amount(BaseModel):
    """One line of a breakdown: a category, a store or a card with what was spent on it.

    `key` is stable across periods (a category value, a store id, a card ending, `cash`) so two
    periods can be compared by it. `label` is the text to show; it is empty when the view owns
    the text (the `cash` card and a receipt without a store).
    """

    model_config = ConfigDict(frozen=True)

    key: str
    label: str
    value: Decimal


class CurrencyBlock(BaseModel):
    """One currency of a period. `total` and `receipt_count` are over parsed receipts;
    `categories` come from item lines (non-zero only, largest first); `not_itemised` is what the
    categories do not cover; `stores` and `cards` come from receipt totals, largest first (cards
    without an ending are under key `cash`)."""

    model_config = ConfigDict(frozen=True)

    currency: str
    total: Decimal
    receipt_count: int
    categories: list[Amount]
    not_itemised: Decimal
    stores: list[Amount]
    cards: list[Amount]


class SpendingPeriod(BaseModel):
    """The spending of the half-open local-date period `[start, end)`, one block per currency
    ordered by currency code."""

    model_config = ConfigDict(frozen=True)

    start: date
    end: date
    blocks: list[CurrencyBlock]
