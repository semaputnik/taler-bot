"""Hand-built receipts and parses for the domain tests."""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

from src.domain.enums import Category
from src.domain.receipt import Parse, ParsedItem, Photo

WHEN = datetime(2026, 10, 14, 18, 32, tzinfo=UTC)


def photo(unique_id: str = "u1", *, id: int | None = None) -> Photo:
    return Photo(
        id=id, telegram_file_unique_id=unique_id, path=f"2026/10/{unique_id}.jpg", received_at=WHEN
    )


def product(
    key: str = "mercadona::leche", total: str = "1.20", quantity: str = "1", **fields
) -> ParsedItem:
    item = ParsedItem(
        product_key=key,
        printed_name=key.split("::")[1].upper(),
        readable_name=key.split("::")[1].capitalize(),
        category=Category.DAIRY,
        quantity=Decimal(quantity),
        unit="pcs",
        unit_price=Decimal(total) / Decimal(quantity),
        line_total=Decimal(total),
    )
    return replace(item, **fields)


def parse(*items: ParsedItem, id: int | None = None, **fields) -> Parse:
    base = Parse(
        id=id,
        store_key="mercadona",
        store_name="Mercadona",
        purchased_at=WHEN,
        receipt_number="0042",
        receipt_key="mercadona|0042|2026-10-14|47.50",
        currency="EUR",
        total=Decimal("47.50"),
        items=items or (product(),),
        raw_output={"is_receipt": True},
        model="test-model",
        parser_version="2026-10-15.1",
    )
    return replace(base, **fields)
