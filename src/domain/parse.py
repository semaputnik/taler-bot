"""`Parse`: one normalized reading of a receipt's photos (what `normalize` produces).

Mirrors the return value of `docs/n8n-reference/normalize_receipt.js`. A value object: frozen,
compared by value, except for the optional `id` the repository assigns once it is stored.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from src.domain.enums import Category, IssueSeverity, IssueSource
from src.exception import InvalidReceiptData


@dataclass(frozen=True, kw_only=True)
class ParsedItem:
    """An item as the parse read it, before any user edit."""

    product_key: str
    printed_name: str
    readable_name: str
    category: Category = Category.OTHER
    quantity: Decimal = Decimal(1)
    unit: str = "pcs"
    unit_price: Decimal | None = None
    reference_price: Decimal | None = None
    reference_unit: str | None = None
    discount: Decimal = Decimal(0)
    line_total: Decimal | None = None
    vat_rate: Decimal | None = None


@dataclass(frozen=True, kw_only=True)
class ParsedIssue:
    """A doubt raised by the model or by normalization."""

    source: IssueSource = IssueSource.MODEL
    issue_type: str = "other"
    severity: IssueSeverity = IssueSeverity.MEDIUM
    field: str | None = None
    item_name: str | None = None  # the printed name of the item it is about
    message: str = ""


@dataclass(frozen=True, kw_only=True)
class Parse:
    id: int | None = None  # None until the repository has stored it (parses are append-only)
    is_receipt: bool = True

    store_key: str | None = None
    store_name: str | None = None
    store_legal_name: str | None = None
    store_address: str | None = None
    store_tax_id: str | None = None

    purchased_at: datetime | None = None
    receipt_number: str | None = None
    receipt_key: str | None = None
    currency: str | None = None
    subtotal: Decimal | None = None
    discount_total: Decimal | None = None
    tax_total: Decimal | None = None
    total: Decimal | None = None
    payment_method: str | None = None
    card_brand: str | None = None
    card_last4: str | None = None

    items: tuple[ParsedItem, ...] = ()
    issues: tuple[ParsedIssue, ...] = ()

    raw_output: dict[str, Any] | None = None
    model: str | None = None
    parser_version: str
    photo_ids: tuple[int, ...] = ()  # the photos this parse was made from

    def __post_init__(self) -> None:
        if self.purchased_at is not None and self.purchased_at.tzinfo is None:
            raise InvalidReceiptData("purchased_at must be timezone-aware")

    @property
    def product_keys(self) -> frozenset[str]:
        return frozenset(item.product_key for item in self.items)


@dataclass(frozen=True)
class ParseOutcome:
    """Which catalog products a parse change touches, for `Catalog` to act on."""

    product_keys_used: frozenset[str]
    # Used by the previous current parse, not by the new one: candidates for removal.
    product_keys_released: frozenset[str]
