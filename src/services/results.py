"""The services' own types: what the bot passes in and gets back (no domain, no database types)."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

from src.database.read_models import (
    Amount,
    CurrencyBlock,
    CurrencyTotal,
    HistoryPage,
    HistoryRow,
    PayeeOption,
    ReparseCandidates,
    SourceOption,
    SpendingPeriod,
)

__all__ = [
    "PAGE_SIZE",
    "Amount",
    "BulkResult",
    "CurrencyBlock",
    "CurrencyTotal",
    "Compared",
    "ComparedBlock",
    "CurrentUser",
    "ExpenseCard",
    "ExpenseDraft",
    "HistoryPage",
    "HistoryRow",
    "IssueCard",
    "IssueLine",
    "ItemRow",
    "NewPhoto",
    "ParseResult",
    "PayeeOption",
    "PhotoRef",
    "ProductCard",
    "ReceiptCard",
    "ReparseCandidates",
    "ReparseSummary",
    "SourceOption",
    "SpendingPeriod",
    "SpendingReport",
]

PAGE_SIZE = 8  # rows of the history per page


class CurrentUser(BaseModel):
    """The user an update comes from, as the bot layer sees them."""

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: int
    username: str | None
    first_name: str | None
    is_allowed: bool
    is_admin: bool
    timezone: str
    default_currency: str


class NewPhoto(BaseModel):
    """A received photo's Telegram ids and metadata; the service decides where its bytes go."""

    model_config = ConfigDict(frozen=True)

    received_at: datetime
    telegram_file_unique_id: str | None = None
    telegram_file_id: str | None = None
    telegram_message_id: int | None = None
    mime_type: str | None = None
    size_bytes: int | None = None


class ReceiptCard(BaseModel):
    """What the summary message of a receipt shows."""

    model_config = ConfigDict(frozen=True)

    receipt_id: int
    status: str
    received_at: datetime
    deleted: bool
    store_key: str | None  # the store's slug, e.g. `ametller-origen`; the card's hashtag
    store_name: str | None
    purchased_at: datetime | None
    currency: str | None
    total: Decimal | None
    payment_method: str | None
    card_brand: str | None
    card_last4: str | None
    item_count: int
    open_issue_count: int
    expense_id: int | None  # the receipt's expense; None while it is not a purchase
    expense_category: str | None  # an `ExpenseCategory` value
    payment_source_name: str | None  # the expense's card or cash, by its name
    review_count: int  # open issues of severity high or medium: what the review walk visits
    can_reparse: bool  # the photo can be read again: parsed, failed or not_receipt, not deleted
    error_message: str | None  # why the last read failed; kept on a restored receipt too
    duplicate_of: ReceiptCard | None = None  # set by `ReceiptService.card` for a duplicate


class ExpenseCard(BaseModel):
    """What an expense shows. A receipt-backed expense has `receipt_id`; its amount, date, payee
    and payment source follow the receipt. `category` is an `ExpenseCategory` value, `tags` are
    sorted, `spent_at` is the user's local day.

    `payee_key` and `payment_source_id` name the payee and the source (for pickers that mark the
    current one); `can_edit_facts` is true for an expense typed by hand, whose amount, payee,
    source and date the user may change (those of a receipt follow the receipt)."""

    model_config = ConfigDict(frozen=True)

    expense_id: int
    amount: Decimal
    currency: str
    spent_at: date
    payee_key: str | None
    payee_name: str | None
    payment_source_id: int | None
    payment_source_name: str | None
    category: str
    tags: list[str]
    receipt_id: int | None
    can_edit_facts: bool
    deleted: bool


class ExpenseDraft(BaseModel):
    """An expense the user typed, as the entry dialog collects it.

    The payee is `payee_key` (one picked from the list) or `payee_name` (typed; an existing
    payee with the same slug is reused), or neither. The source is `payment_source_id` (one
    picked), `cash`, or `new_card_name` (a card to create), or none. At most one of each group.
    `category` is an `ExpenseCategory` value; `tags` are free words, normalised by the domain.
    """

    model_config = ConfigDict(frozen=True)

    amount: Decimal
    spent_at: date
    category: str = "other"
    payee_key: str | None = None
    payee_name: str | None = None
    payment_source_id: int | None = None
    new_card_name: str | None = None
    cash: bool = False
    tags: list[str] = []


class ItemRow(BaseModel):
    """One item of a receipt with the user's edits applied, for the item list and item view."""

    model_config = ConfigDict(frozen=True)

    ref: str
    product_key: str  # the catalog product behind the item: rename and category act on it
    currency: str | None  # the receipt's; items carry no currency of their own
    printed_name: str
    readable_name: str
    category: str
    quantity: Decimal
    unit: str
    unit_price: Decimal | None
    reference_price: Decimal | None
    reference_unit: str | None
    discount: Decimal
    line_total: Decimal | None
    vat_rate: Decimal | None


class ProductCard(BaseModel):
    """A catalog product as the user sees it: the printed text, the name and the category."""

    model_config = ConfigDict(frozen=True)

    product_key: str
    store_key: str
    printed_name: str
    name: str
    category: str


class PhotoRef(BaseModel):
    """What Telegram knows of a receipt's photo: enough to show it without reading the disk."""

    model_config = ConfigDict(frozen=True)

    telegram_file_id: str | None
    mime_type: str | None


class IssueLine(BaseModel):
    """One doubt for the summary: which item it is about (if any) and what it says."""

    model_config = ConfigDict(frozen=True)

    item_name: str | None
    message: str


class IssueCard(BaseModel):
    """One issue of the review walk, with what the user can do about it.

    `editable` is true when a typed value can fix it; `input_kind` then says what to ask for
    (`datetime`, `text`, `currency`, `money`, `number` or `last4`) and `current_value` is what
    the receipt holds now (a `Decimal`, an aware `datetime` or a `str`; None when empty).
    `item_name` is the readable name of the item the issue is about, else the issue's own text.
    `product_key` is that item's product for an `items.*` issue with a matched item, else None;
    `renamable` is true for a name issue (`items.name_raw`, `items.name_normalized`) with one.
    """

    model_config = ConfigDict(frozen=True)

    issue_id: int
    severity: str
    source: str
    issue_type: str
    field: str | None
    item_name: str | None
    product_key: str | None
    renamable: bool
    message: str
    editable: bool
    input_kind: str | None
    current_value: Decimal | datetime | str | None


class ParseResult(BaseModel):
    """How a parse ended, with what the reply needs.

    `issues` are the most severe ones (at most five, high first, then in parse order);
    `duplicate_of` is set for `duplicate`, `error` for `failed`.
    """

    model_config = ConfigDict(frozen=True)

    card: ReceiptCard
    outcome: Literal["parsed", "not_receipt", "duplicate", "failed"]
    duplicate_of: ReceiptCard | None = None
    issues: list[IssueLine] = []
    error: str | None = None


class ReparseSummary(BaseModel):
    """What a bulk re-parse would read: counts per reason and the current parser version."""

    model_config = ConfigDict(frozen=True)

    failed_count: int
    outdated_count: int
    parser_version: str


class BulkResult(BaseModel):
    """How a bulk re-parse ended: receipts read again, and receipts that failed again."""

    model_config = ConfigDict(frozen=True)

    ok: int
    failed: int


class Compared(BaseModel):
    """One line of a breakdown set against the previous period.

    `share` is the value as a whole percent of its block's total. `previous` is the same line's
    value in the previous period, None when that period had no such line (the view says "new");
    `change` is the whole percent against `previous`, None when `previous` is missing or zero.
    `key` is `not_itemised` for the remainder no item line covers (its `label` is empty).
    """

    model_config = ConfigDict(frozen=True)

    key: str
    label: str
    value: Decimal
    share: int
    previous: Decimal | None
    change: int | None


class ComparedBlock(BaseModel):
    """One currency of a period against the previous period. `previous_total` is None when the
    previous period had no expenses in this currency; `change` is the whole percent of the total
    against it, None when it is missing or zero. `categories` are by expense category; `products`
    are by product category and end with the `not_itemised` line when it is at least 0.01 in
    size; `payees` holds the five largest; `sources` all of them."""

    model_config = ConfigDict(frozen=True)

    currency: str
    total: Decimal
    previous_total: Decimal | None
    change: int | None
    expense_count: int
    categories: list[Compared]
    products: list[Compared]
    payees: list[Compared]
    sources: list[Compared]


class SpendingReport(BaseModel):
    """A week or month of spending for the stats screen, in the user's time zone. `[start, end)`
    are local dates; `is_current` says the period holds today; `has_earlier` says an expense was
    made before `start`. `blocks` hold the user's default currency first, then the others
    alphabetically; a period with no expenses has none."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["week", "month"]
    start: date
    end: date
    is_current: bool
    has_earlier: bool
    blocks: list[ComparedBlock]
