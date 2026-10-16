from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    ForeignKey,
    Identity,
    Index,
    Numeric,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.database.models.base import Base, CreatedAt, Money, Quantity, Timestamps, enum_check
from src.domain.enums import (
    EditTarget,
    IssueResolution,
    IssueSeverity,
    IssueSource,
    ParseStatus,
    ReceiptStatus,
)


class Receipt(Timestamps, Base):
    """One purchase receipt with one photo and at most one parse (ADR-0002). Replaces n8n
    `receipt_payments`.

    The header columns (store_id … card_last4) are a denormalized copy of the parse with the
    user's edits applied, so lists and stats never read JSON.
    """

    __tablename__ = "receipts"
    __table_args__ = (
        enum_check("status", ReceiptStatus),
        CheckConstraint(r"card_last4 ~ '^\d{4}$'", name="card_last4"),
        CheckConstraint(
            "(status = 'duplicate') = (duplicate_of_id IS NOT NULL)", name="duplicate_of"
        ),
        UniqueConstraint("source_ref"),
        # The dedupe key n8n checked by hand; a repeat is marked `duplicate`, so it never collides.
        Index(
            "uq_receipts_user_id_receipt_key_parsed",
            "user_id",
            "receipt_key",
            unique=True,
            postgresql_where=text("status = 'parsed' AND deleted_at IS NULL"),
        ),
        Index("ix_receipts_user_id_purchased_at", "user_id", "purchased_at"),
        Index("ix_receipts_user_id_store_id_purchased_at", "user_id", "store_id", "purchased_at"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(server_default=ReceiptStatus.PENDING.value)
    # The earlier receipt this one repeats; set exactly when status is 'duplicate'.
    duplicate_of_id: Mapped[int | None] = mapped_column(
        ForeignKey("receipts.id", ondelete="SET NULL")
    )

    store_id: Mapped[int | None] = mapped_column(ForeignKey("stores.id", ondelete="SET NULL"))
    receipt_key: Mapped[str | None]
    receipt_number: Mapped[str | None]
    purchased_at: Mapped[datetime | None]
    currency: Mapped[str | None] = mapped_column(CHAR(3))
    subtotal: Mapped[Money | None]
    discount_total: Mapped[Money | None]
    tax_total: Mapped[Money | None]
    total: Mapped[Money | None]
    payment_method: Mapped[str | None]
    card_brand: Mapped[str | None]
    card_last4: Mapped[str | None] = mapped_column(CHAR(4))

    error_message: Mapped[str | None]
    deleted_at: Mapped[datetime | None]
    # "n8n:<row id>" for imported rows, so the import can be rerun safely.
    source_ref: Mapped[str | None]


class ReceiptPhoto(CreatedAt, Base):
    """The one photo of a receipt."""

    __tablename__ = "receipt_photos"
    __table_args__ = (
        # The same image sent twice is answered without an LLM call.
        UniqueConstraint("user_id", "telegram_file_unique_id"),
        # Photos imported from n8n live in Google Drive until they are downloaded.
        CheckConstraint("path IS NOT NULL OR drive_file_id IS NOT NULL", name="has_location"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    receipt_id: Mapped[int] = mapped_column(
        ForeignKey("receipts.id", ondelete="CASCADE"), unique=True
    )
    # Denormalized from the receipt for the unique index above.
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    # Relative to RECEIPTS_DIR.
    path: Mapped[str | None]
    mime_type: Mapped[str | None]
    size_bytes: Mapped[int | None]
    telegram_file_id: Mapped[str | None]
    telegram_file_unique_id: Mapped[str | None]
    telegram_message_id: Mapped[int | None]
    drive_file_id: Mapped[str | None]
    drive_url: Mapped[str | None]
    received_at: Mapped[datetime]


class ReceiptParse(CreatedAt, Base):
    """The reading of a receipt's photo. A re-parse replaces the row."""

    __tablename__ = "receipt_parses"
    __table_args__ = (enum_check("status", ParseStatus),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    receipt_id: Mapped[int] = mapped_column(
        ForeignKey("receipts.id", ondelete="CASCADE"), unique=True
    )
    status: Mapped[str]
    parser_version: Mapped[str]
    model: Mapped[str | None]
    raw_output: Mapped[dict[str, Any] | None]
    # Normalize output before user edits; item rebuilds use it without calling the LLM.
    normalized: Mapped[dict[str, Any] | None]
    error: Mapped[str | None]
    input_tokens: Mapped[int | None]
    output_tokens: Mapped[int | None]
    duration_ms: Mapped[int | None]


class ReceiptItem(Base):
    """A line of the parse. Replaces n8n `product_prices`; rebuilt on parse change."""

    __tablename__ = "receipt_items"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    receipt_id: Mapped[int] = mapped_column(
        ForeignKey("receipts.id", ondelete="CASCADE"), index=True
    )
    store_product_id: Mapped[int] = mapped_column(
        ForeignKey("store_products.id", ondelete="RESTRICT"), index=True
    )
    position: Mapped[int]
    name_raw: Mapped[str]
    quantity: Mapped[Quantity]
    unit: Mapped[str]
    unit_price: Mapped[Quantity | None]
    reference_price: Mapped[Quantity | None]
    reference_unit: Mapped[str | None]
    discount: Mapped[Money] = mapped_column(server_default=text("0"))
    line_total: Mapped[Money | None]
    vat_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    barcode: Mapped[str | None]


class ReceiptIssue(CreatedAt, Base):
    """A problem noted while reading a receipt, belonging to its parse."""

    __tablename__ = "receipt_issues"
    __table_args__ = (
        enum_check("source", IssueSource),
        enum_check("severity", IssueSeverity),
        enum_check("resolution", IssueResolution),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    parse_id: Mapped[int] = mapped_column(
        ForeignKey("receipt_parses.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[str]
    issue_type: Mapped[str]
    severity: Mapped[str]
    field: Mapped[str | None]
    item_name_raw: Mapped[str | None]
    message: Mapped[str]
    resolution: Mapped[str] = mapped_column(server_default=IssueResolution.OPEN.value)
    resolved_at: Mapped[datetime | None]


class ReceiptEdit(CreatedAt, Base):
    """A value the user corrected by hand. Applied after normalize, so it wins over any parse.

    Product name and category edits are not stored here; they go to store_products.
    """

    __tablename__ = "receipt_edits"
    __table_args__ = (
        enum_check("target", EditTarget),
        CheckConstraint("(target = 'item') = (item_ref IS NOT NULL)", name="item_ref"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    receipt_id: Mapped[int] = mapped_column(
        ForeignKey("receipts.id", ondelete="CASCADE"), index=True
    )
    target: Mapped[str]
    # "<product_key>#<occurrence>": item ids change on every rebuild, product keys do not.
    item_ref: Mapped[str | None]
    field: Mapped[str]
    value: Mapped[Any] = mapped_column(JSONB)
    issue_id: Mapped[int | None] = mapped_column(
        ForeignKey("receipt_issues.id", ondelete="SET NULL")
    )
