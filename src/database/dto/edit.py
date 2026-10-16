from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class NewReceiptEditDTO(BaseModel):
    receipt_id: int
    # Plain string: the database CHECK is the single source of truth for valid values.
    target: str
    field: str
    value: Any
    item_ref: str | None = None
    issue_id: int | None = None


class ReceiptEditDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: int
    receipt_id: int
    target: str
    field: str
    value: Any
    item_ref: str | None
    issue_id: int | None
    created_at: datetime
