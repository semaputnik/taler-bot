"""ORM rows <-> the `Receipt` aggregate and its parts.

The only module that knows both. Rows never leave `database`; the aggregate never sees them.
`*_values` build column dicts for INSERT/UPDATE, `*_from_row` build domain objects.
"""

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any

from src.database.models import (
    Receipt as ReceiptRow,
)
from src.database.models import (
    ReceiptEdit,
    ReceiptIssue,
    ReceiptItem,
    ReceiptParse,
    ReceiptPhoto,
    StoreProduct,
)
from src.domain.edits import Edit
from src.domain.enums import (
    Category,
    EditTarget,
    IssueResolution,
    IssueSeverity,
    IssueSource,
    ParseStatus,
    ReceiptStatus,
)
from src.domain.parse import Parse, ParsedIssue, ParsedItem
from src.domain.receipt import Header, Issue, Item, Photo, Receipt

# --- header ------------------------------------------------------------------------------

_HEADER_COLUMNS = (
    "receipt_key",
    "receipt_number",
    "purchased_at",
    "currency",
    "subtotal",
    "discount_total",
    "tax_total",
    "total",
    "payment_method",
    "card_brand",
    "card_last4",
)


def receipt_values(receipt: Receipt, *, store_id: int | None) -> dict[str, Any]:
    """The `receipts` row of the aggregate (everything but its own id and timestamps)."""
    current = receipt.current_parse
    return {
        "user_id": receipt.user_id,
        "status": receipt.status.value,
        "current_parse_id": current.id if current is not None else None,
        "merged_into_id": receipt.merged_into_id,
        "store_id": store_id,
        "error_message": receipt.error_message,
        "deleted_at": receipt.deleted_at,
        **{column: getattr(receipt.header, column) for column in _HEADER_COLUMNS},
    }


def receipt_from_rows(
    row: ReceiptRow,
    store_key: str | None,
    photos: Sequence[ReceiptPhoto],
    parses: Sequence[ReceiptParse],
    items: Sequence[tuple[ReceiptItem, StoreProduct]],
    issues: Sequence[ReceiptIssue],
    edits: Sequence[ReceiptEdit],
) -> Receipt:
    domain_parses = [parse_from_row(p) for p in parses]
    current = next((p for p in domain_parses if p.id == row.current_parse_id), None)
    receipt = Receipt(
        id=row.id,
        user_id=row.user_id,
        status=ReceiptStatus(row.status),
        # No store row yet (the catalog adds it later): the current parse still names it.
        header=Header(
            store_key=store_key or (current.store_key if current is not None else None),
            **{column: getattr(row, column) for column in _HEADER_COLUMNS},
        ),
        photos=[photo_from_row(p) for p in photos],
        parses=domain_parses,
        current_parse=current,
        items=_items_from_rows(items),
        issues=[issue_from_row(i) for i in issues],
        edits=[edit_from_row(e) for e in edits],
        merged_into_id=row.merged_into_id,
        deleted_at=row.deleted_at,
        error_message=row.error_message,
    )
    return receipt


# --- photos ------------------------------------------------------------------------------


def photo_values(photo: Photo, *, receipt: Receipt, position: int) -> dict[str, Any]:
    return {
        "receipt_id": receipt.id,
        "user_id": receipt.user_id,
        "position": position,
        "path": photo.path,
        "mime_type": photo.mime_type,
        "size_bytes": photo.size_bytes,
        "telegram_file_id": photo.telegram_file_id,
        "telegram_file_unique_id": photo.telegram_file_unique_id,
        "telegram_message_id": photo.telegram_message_id,
        "received_at": photo.received_at,
    }


def photo_from_row(row: ReceiptPhoto) -> Photo:
    return Photo(
        id=row.id,
        path=row.path,
        mime_type=row.mime_type,
        size_bytes=row.size_bytes,
        telegram_file_id=row.telegram_file_id,
        telegram_file_unique_id=row.telegram_file_unique_id,
        telegram_message_id=row.telegram_message_id,
        received_at=row.received_at,
    )


# --- parses ------------------------------------------------------------------------------
# `normalized` holds the Parse minus the fields that have their own columns. Decimal is
# written as str and datetime as ISO text, so nothing is lost to JSON floats.

_PARSE_COLUMNS = {"id", "raw_output", "model", "parser_version", "photo_ids"}
_PARSE_MONEY = (
    "subtotal",
    "discount_total",
    "tax_total",
    "total",
)
_ITEM_NUMBERS = (
    "quantity",
    "unit_price",
    "reference_price",
    "discount",
    "line_total",
    "vat_rate",
)


def parse_values(parse: Parse, *, receipt_id: int | None) -> dict[str, Any]:
    return {
        "receipt_id": receipt_id,
        "status": ParseStatus.OK.value,
        "parser_version": parse.parser_version,
        "model": parse.model,
        "photo_ids": list(parse.photo_ids),
        "raw_output": parse.raw_output,
        "normalized": normalized_of(parse),
    }


def normalized_of(parse: Parse) -> dict[str, Any]:
    dump: dict[str, Any] = {
        name: _dump(getattr(parse, name))
        for name in Parse.__dataclass_fields__
        if name not in _PARSE_COLUMNS | {"items", "issues"}
    }
    dump["items"] = [
        {name: _dump(getattr(item, name)) for name in ParsedItem.__dataclass_fields__}
        for item in parse.items
    ]
    dump["issues"] = [
        {name: _dump(getattr(issue, name)) for name in ParsedIssue.__dataclass_fields__}
        for issue in parse.issues
    ]
    return dump


def parse_from_row(row: ReceiptParse) -> Parse:
    common = {
        "id": row.id,
        "raw_output": row.raw_output,
        "model": row.model,
        "parser_version": row.parser_version,
        "photo_ids": tuple(row.photo_ids),
    }
    data = row.normalized
    if data is None:  # a reading that produced nothing usable: only what the columns say
        return Parse(is_receipt=False, **common)
    fields = {
        name: _load(name, value) for name, value in data.items() if name not in ("items", "issues")
    }
    items = tuple(
        ParsedItem(**{name: _load_item(name, value) for name, value in item.items()})
        for item in data["items"]
    )
    issues = tuple(
        ParsedIssue(**{name: _load_issue(name, value) for name, value in issue.items()})
        for issue in data["issues"]
    )
    return Parse(**common, **fields, items=items, issues=issues)


def _dump(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Category | IssueSource | IssueSeverity):
        return value.value
    return value


def _load(name: str, value: Any) -> Any:
    if value is None:
        return None
    if name in _PARSE_MONEY:
        return Decimal(value)
    if name == "purchased_at":
        return datetime.fromisoformat(value)
    return value


def _load_item(name: str, value: Any) -> Any:
    if value is None:
        return None
    if name in _ITEM_NUMBERS:
        return Decimal(value)
    if name == "category":
        return Category(value)
    return value


def _load_issue(name: str, value: Any) -> Any:
    if name == "source":
        return IssueSource(value)
    if name == "severity":
        return IssueSeverity(value)
    return value


# --- items -------------------------------------------------------------------------------


def item_values(
    item: Item, *, receipt_id: int | None, position: int, product_id: int
) -> dict[str, Any]:
    return {
        "receipt_id": receipt_id,
        "store_product_id": product_id,
        "position": position,
        "name_raw": item.printed_name,
        "quantity": item.quantity,
        "unit": item.unit,
        "unit_price": item.unit_price,
        "reference_price": item.reference_price,
        "reference_unit": item.reference_unit,
        "discount": item.discount,
        "line_total": item.line_total,
        "vat_rate": item.vat_rate,
    }


def _items_from_rows(rows: Sequence[tuple[ReceiptItem, StoreProduct]]) -> list[Item]:
    """Rows in position order; the product row gives the key, readable name and category."""
    seen: dict[str, int] = {}
    items = []
    for row, product in rows:
        seen[product.product_key] = seen.get(product.product_key, 0) + 1
        items.append(
            Item(
                ref=f"{product.product_key}#{seen[product.product_key]}",
                product_key=product.product_key,
                printed_name=row.name_raw,
                readable_name=product.name,
                category=Category(product.category),
                quantity=row.quantity,
                unit=row.unit,
                unit_price=row.unit_price,
                reference_price=row.reference_price,
                reference_unit=row.reference_unit,
                discount=row.discount,
                line_total=row.line_total,
                vat_rate=row.vat_rate,
            )
        )
    return items


# --- issues ------------------------------------------------------------------------------


def issue_values(issue: Issue, *, parse_id: int | None) -> dict[str, Any]:
    return {
        "parse_id": parse_id,
        "source": issue.source.value,
        "issue_type": issue.issue_type,
        "severity": issue.severity.value,
        "field": issue.field,
        "item_name_raw": issue.item_name,
        "message": issue.message,
        "resolution": issue.resolution.value,
        "resolved_at": issue.resolved_at,
    }


def issue_from_row(row: ReceiptIssue) -> Issue:
    return Issue(
        id=row.id,
        source=IssueSource(row.source),
        issue_type=row.issue_type,
        severity=IssueSeverity(row.severity),
        field=row.field,
        item_name=row.item_name_raw,
        message=row.message,
        resolution=IssueResolution(row.resolution),
        resolved_at=row.resolved_at,
    )


# --- edits -------------------------------------------------------------------------------


def edit_values(edit: Edit, *, receipt_id: int | None) -> dict[str, Any]:
    return {
        "receipt_id": receipt_id,
        "target": edit.target.value,
        "item_ref": edit.item_ref,
        "field": edit.field,
        "value": _dump(edit.value),
        "issue_id": edit.issue_id,
    }


def edit_from_row(row: ReceiptEdit) -> Edit:
    return Edit(
        id=row.id,
        target=EditTarget(row.target),
        item_ref=row.item_ref,
        field=row.field,
        value=row.value,
        issue_id=row.issue_id,
    )
