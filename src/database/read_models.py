"""Read models: pydantic shapes for a screen, returned by repository query methods.

They are not aggregates. The services re-export them from `services.results`, so `bot` imports
them from `services` only.
"""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class HistoryRow(BaseModel):
    """One row of the month: an expense, or a receipt that has no expense. `day` is the local
    day.

    A row backed by a receipt carries `receipt_id` and the receipt's `status`, so the history
    can show a status icon and open the receipt card; an expense without a receipt has
    `has_receipt` false and both empty. A receipt that is not a purchase (failed, not a receipt,
    duplicate, pending, parsing) has no expense: `expense_id`, `amount`, `currency` and
    `category` are empty and `has_receipt` is true.
    """

    model_config = ConfigDict(frozen=True)

    expense_id: int | None
    receipt_id: int | None
    has_receipt: bool
    day: date
    payee_name: str | None
    amount: Decimal | None
    currency: str | None
    category: str | None  # an `ExpenseCategory` value
    status: str | None


class CurrencyTotal(BaseModel):
    model_config = ConfigDict(frozen=True)

    currency: str
    amount: Decimal


class PayeeOption(BaseModel):
    """A payee to pick: its id (for a filter), its key (for an expense) and its name."""

    model_config = ConfigDict(frozen=True)

    payee_id: int
    payee_key: str
    name: str


class SourceOption(BaseModel):
    """A payment source to pick; `kind` is a `PaymentSourceKind` value (`card` or `cash`)."""

    model_config = ConfigDict(frozen=True)

    id: int
    name: str
    kind: str


class HistoryPage(BaseModel):
    """One page of one month of a user's expenses and receipts without an expense, with what
    the header and the buttons need.

    `rows` is the requested page of the month under the payee filter, newest first;
    `total_rows` counts all of the month's rows under the filter (for paging), `expense_count`
    those that are expenses. `totals` (one entry per currency) sum the expenses only. `payees`
    are the payees with a row in the month, whatever the filter. `has_earlier` / `has_later` say
    whether any row of the user lies before / after the month, whatever the filter. `payee_name`
    is the filter's payee, None without a filter or for a payee that is not the user's.
    """

    model_config = ConfigDict(frozen=True)

    year: int
    month: int
    rows: list[HistoryRow]
    total_rows: int
    expense_count: int
    totals: list[CurrencyTotal]
    payees: list[PayeeOption]
    has_earlier: bool
    has_later: bool
    payee_name: str | None


class ReparseCandidates(BaseModel):
    """The ids of a user's receipts worth reading again, oldest first.

    `failed_ids` are receipts whose last read failed; `outdated_ids` are parsed or not-receipt
    receipts read by a parser other than the current version.
    """

    model_config = ConfigDict(frozen=True)

    failed_ids: list[int]
    outdated_ids: list[int]


class Amount(BaseModel):
    """One line of a breakdown: a category, a payee or a payment source with what was spent.

    `key` is stable across periods (a category value, a payee id, a card ending, `cash`; `none`
    for an expense without a payee or a source) so two periods can be compared by it. `label`
    is the text to show: the payee's or the source's name, the category value for a category.
    It is empty for `none`.
    """

    model_config = ConfigDict(frozen=True)

    key: str
    label: str
    value: Decimal


class CurrencyBlock(BaseModel):
    """One currency of a period, over the user's not deleted expenses.

    `total` and `expense_count` count every expense. `categories` are by expense category
    (`ExpenseCategory` values, non-zero only, largest first); `products` are by product
    category over the item lines of the receipt-backed expenses (`ProductCategory` values,
    non-zero only, largest first); `not_itemised` is what the receipt-backed expenses spent
    beyond those item lines. `payees` and `sources` are by expense amount, largest first; the
    cash source has key `cash`.
    """

    model_config = ConfigDict(frozen=True)

    currency: str
    total: Decimal
    expense_count: int
    categories: list[Amount]
    products: list[Amount]
    not_itemised: Decimal
    payees: list[Amount]
    sources: list[Amount]


class SpendingPeriod(BaseModel):
    """The spending of the half-open local-date period `[start, end)`, one block per currency
    ordered by currency code."""

    model_config = ConfigDict(frozen=True)

    start: date
    end: date
    blocks: list[CurrencyBlock]
