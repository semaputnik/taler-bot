"""The services' own types: what the bot passes in and gets back (no domain, no database types)."""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

from src.database.read_models import CurrencyTotal, HistoryPage, HistoryRow, StoreOption

__all__ = [
    "PAGE_SIZE",
    "CurrencyTotal",
    "CurrentUser",
    "HistoryPage",
    "HistoryRow",
    "IssueCard",
    "IssueLine",
    "ItemRow",
    "NewPhoto",
    "ParseResult",
    "PhotoRef",
    "ProductCard",
    "ReceiptCard",
    "StoreOption",
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
    review_count: int  # open issues of severity high or medium: what the review walk visits
    duplicate_of: ReceiptCard | None = None  # set by `ReceiptService.card` for a duplicate


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
