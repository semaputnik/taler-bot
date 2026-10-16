from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class NewReceiptParseDTO(BaseModel):
    receipt_id: int
    # Plain strings: the database CHECK is the single source of truth for valid values.
    status: str
    parser_version: str
    photo_ids: list[int]
    model: str | None = None
    raw_output: dict[str, Any] | None = None
    normalized: dict[str, Any] | None = None
    error: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    duration_ms: int | None = None


class ReceiptParseDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: int
    receipt_id: int
    status: str
    parser_version: str
    photo_ids: list[int]
    model: str | None
    raw_output: dict[str, Any] | None
    normalized: dict[str, Any] | None
    error: str | None
    input_tokens: int | None
    output_tokens: int | None
    duration_ms: int | None
    created_at: datetime
