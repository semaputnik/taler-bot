from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from src.domain.enums import ReceiptStatus


class NewReceiptDTO(BaseModel):
    user_id: int
    # Plain string: the database CHECK is the single source of truth for valid values.
    status: str = ReceiptStatus.PENDING.value
    store_id: int | None = None
    receipt_key: str | None = None
    merged_into_id: int | None = None
    card_last4: str | None = None
    deleted_at: datetime | None = None


class ReceiptDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: int
    user_id: int
    status: str
    store_id: int | None
    receipt_key: str | None
    merged_into_id: int | None
    card_last4: str | None
    deleted_at: datetime | None


class NewReceiptItemDTO(BaseModel):
    receipt_id: int
    store_product_id: int
    position: int
    name_raw: str
    quantity: Decimal
    unit: str


class ReceiptItemDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: int
    receipt_id: int
    store_product_id: int
    position: int
    name_raw: str
    quantity: Decimal
    unit: str
    discount: Decimal
