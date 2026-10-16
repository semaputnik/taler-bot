"""The services' own types: what the bot passes in and gets back (no domain, no database types)."""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict


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
    store_name: str | None
    purchased_at: datetime | None
    currency: str | None
    total: Decimal | None
    payment_method: str | None
    card_brand: str | None
    card_last4: str | None
    item_count: int
    open_issue_count: int
    duplicate_of: ReceiptCard | None = None  # set by `ReceiptService.card` for a duplicate


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
