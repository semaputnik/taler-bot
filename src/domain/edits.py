"""`Edit`: a value the user corrected by hand, and what a field may hold."""

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from src.domain.enums import EditTarget
from src.exception import InvalidEdit

# Item fields that must be positive / not negative (a misread sign or a zero quantity).
_POSITIVE_ITEM_FIELDS = frozenset({"quantity"})
_NON_NEGATIVE_ITEM_FIELDS = frozenset({"unit_price", "reference_price", "line_total", "discount"})

# field -> (kind, nullable). "money" fields are compared with the 0.02 tolerance, "number"
# fields exactly.
#  Product names and categories are edited on the Catalog, not here.
RECEIPT_FIELDS: dict[str, tuple[str, bool]] = {
    "purchased_at": ("datetime", True),
    "receipt_number": ("text", True),
    "currency": ("text", True),
    "subtotal": ("money", True),
    "discount_total": ("money", True),
    "tax_total": ("money", True),
    "total": ("money", True),
    "payment_method": ("text", True),
    "card_brand": ("text", True),
    "card_last4": ("last4", True),
}
ITEM_FIELDS: dict[str, tuple[str, bool]] = {
    "quantity": ("number", False),
    "unit": ("text", False),
    "unit_price": ("number", True),
    "reference_price": ("number", True),
    "reference_unit": ("text", True),
    "discount": ("money", False),
    "line_total": ("money", True),
    "vat_rate": ("number", True),
}


@dataclass(frozen=True)
class IssueField:
    """The editable field an issue's `field` stands for, and the input the bot asks for.

    `input_kind` is not the field's `kind` above: the issue screen also tells a currency code
    apart from free text.
    """

    target: EditTarget
    field: str
    input_kind: str


# Domain knowledge: which issue `field` (the model's and normalization's vocabulary) is which
# editable field. An issue whose field is not here cannot be fixed by typing a value.
ISSUE_FIELDS: dict[str, IssueField] = {
    key: IssueField(target, field, kind)
    for key, target, field, kind in [
        ("receipt.purchased_at", EditTarget.RECEIPT, "purchased_at", "datetime"),
        ("receipt.number", EditTarget.RECEIPT, "receipt_number", "text"),
        ("currency", EditTarget.RECEIPT, "currency", "currency"),
        ("totals.total", EditTarget.RECEIPT, "total", "money"),
        ("totals.subtotal", EditTarget.RECEIPT, "subtotal", "money"),
        ("totals.discount_total", EditTarget.RECEIPT, "discount_total", "money"),
        ("totals.tax_total", EditTarget.RECEIPT, "tax_total", "money"),
        ("payment.method", EditTarget.RECEIPT, "payment_method", "text"),
        ("payment.card_last4", EditTarget.RECEIPT, "card_last4", "last4"),
        ("items.quantity", EditTarget.ITEM, "quantity", "number"),
        ("items.unit_price", EditTarget.ITEM, "unit_price", "number"),
        ("items.reference_price", EditTarget.ITEM, "reference_price", "number"),
        ("items.discount", EditTarget.ITEM, "discount", "money"),
        ("items.line_total", EditTarget.ITEM, "line_total", "money"),
        ("items.vat_rate", EditTarget.ITEM, "vat_rate", "number"),
    ]
}


@dataclass(kw_only=True)
class Edit:
    target: EditTarget
    field: str
    value: Any  # JSON-compatible as stored; `Receipt` coerces it to the field's type
    item_ref: str | None = None  # "<product_key>#<occurrence>", only for item edits
    issue_id: int | None = None  # the issue the user answered with this edit
    id: int | None = None  # None until stored (edits are append-only)

    def __post_init__(self) -> None:
        if (self.target is EditTarget.ITEM) != (self.item_ref is not None):
            raise InvalidEdit("an edit has an item_ref if and only if it targets an item")
        fields = ITEM_FIELDS if self.target is EditTarget.ITEM else RECEIPT_FIELDS
        if self.field not in fields:
            raise InvalidEdit(f"{self.target} field {self.field!r} cannot be edited")
        self.coerced()  # fail now, not on the next rebuild

    def coerced(self) -> Any:
        """The value as the field holds it: Decimal, aware datetime or str."""
        fields = ITEM_FIELDS if self.target is EditTarget.ITEM else RECEIPT_FIELDS
        kind, nullable = fields[self.field]
        if self.value is None:
            if not nullable:
                raise InvalidEdit(f"{self.field} cannot be cleared")
            return None
        try:
            if kind in ("money", "number"):
                number = Decimal(str(self.value))
                if not number.is_finite():
                    raise InvalidEdit(f"{self.value!r} is not a valid {self.field}")
                if self.target is EditTarget.ITEM:
                    if self.field in _POSITIVE_ITEM_FIELDS and number <= 0:
                        raise InvalidEdit(f"{self.field} must be greater than 0")
                    if self.field in _NON_NEGATIVE_ITEM_FIELDS and number < 0:
                        raise InvalidEdit(f"{self.field} cannot be negative")
                return number
            if kind == "datetime":
                value = (
                    self.value
                    if isinstance(self.value, datetime)
                    else datetime.fromisoformat(self.value)
                )
                if value.tzinfo is None:
                    raise InvalidEdit("purchased_at must be timezone-aware")
                return value
            text = str(self.value)
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise InvalidEdit(f"{self.value!r} is not a valid {self.field}") from exc
        if kind == "last4" and not re.fullmatch(r"\d{4}", text):
            raise InvalidEdit("card_last4 must be 4 digits")
        return text
