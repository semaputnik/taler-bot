"""`RawParse`: the model's output contract, mirroring `docs/n8n-reference/receipt_schema.json`.

Field by field, with the same names, nullability and enums. `integration/llm` validates the
model's answer with `RawParse` and hands `model_dump()` to `domain.normalize`, which takes
plain data.
"""

import warnings
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field


class IssueType(StrEnum):
    UNREADABLE = "unreadable"
    AMBIGUOUS = "ambiguous"
    TOTALS_MISMATCH = "totals_mismatch"
    MISSING_FIELD = "missing_field"
    UNKNOWN_ABBREVIATION = "unknown_abbreviation"
    LAYOUT = "layout"
    OTHER = "other"


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RawStore(BaseModel):
    name: str | None  # brand / trading name, e.g. Mercadona
    legal_name: str | None
    address: str | None
    city: str | None
    country: str | None  # ISO 3166-1 alpha-2
    tax_id: str | None  # NIF/CIF/VAT/INN
    phone: str | None


with warnings.catch_warnings():
    # The schema's field is called `register`, which shadows a BaseModel attribute; the name is the
    # model's contract, so it stays.
    warnings.simplefilter("ignore", UserWarning)

    class RawReceiptInfo(BaseModel):
        number: str | None
        purchased_at: str | None  # local date-time as printed, ISO 8601 without offset
        cashier: str | None
        # `Field(...)`: without it the inherited `BaseModel.register` becomes the default.
        register: str | None = Field(...)


class RawItem(BaseModel):
    name_raw: str  # line text exactly as printed
    name_normalized: str  # clean readable name, no prices or codes
    category: str | None
    quantity: Decimal | None
    unit: str | None  # pcs, kg, g, l or ml
    unit_price: Decimal | None
    reference_price: Decimal | None  # printed price per kg / per l
    reference_unit: str | None
    discount: Decimal | None  # positive number
    line_total: Decimal | None  # after the line discount
    vat_rate: Decimal | None
    barcode: str | None


class RawTax(BaseModel):
    rate: Decimal | None
    base: Decimal | None
    amount: Decimal | None


class RawTotals(BaseModel):
    subtotal: Decimal | None
    discount_total: Decimal | None
    tax_total: Decimal | None
    total: Decimal | None  # final amount paid
    taxes: list[RawTax]


class RawPayment(BaseModel):
    method: str | None  # card, cash, mixed or other
    card_brand: str | None
    card_last4: str | None
    amount_paid: Decimal | None
    change: Decimal | None
    auth_code: str | None
    terminal: str | None


class RawLoyalty(BaseModel):
    program: str | None
    card_number_masked: str | None
    points_earned: Decimal | None
    savings: Decimal | None


class RawIssue(BaseModel):
    type: IssueType
    severity: Severity
    field: str | None  # schema path, e.g. items.unit_price
    item_name_raw: str | None
    message: str


class RawParse(BaseModel):
    is_receipt: bool  # false if the image is not a purchase receipt or is unreadable
    store: RawStore
    receipt: RawReceiptInfo
    currency: str | None  # ISO 4217
    items: list[RawItem]
    totals: RawTotals
    payment: RawPayment
    loyalty: RawLoyalty
    issues: list[RawIssue]
