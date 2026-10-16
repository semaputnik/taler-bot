from datetime import datetime

from pydantic import BaseModel, ConfigDict


class NewReceiptPhotoDTO(BaseModel):
    receipt_id: int
    user_id: int
    received_at: datetime
    position: int = 0
    path: str | None = None
    mime_type: str | None = None
    size_bytes: int | None = None
    telegram_file_id: str | None = None
    telegram_file_unique_id: str | None = None
    telegram_message_id: int | None = None
    drive_file_id: str | None = None
    drive_url: str | None = None


class ReceiptPhotoDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: int
    receipt_id: int
    user_id: int
    received_at: datetime
    position: int
    path: str | None
    mime_type: str | None
    size_bytes: int | None
    telegram_file_id: str | None
    telegram_file_unique_id: str | None
    telegram_message_id: int | None
    drive_file_id: str | None
    drive_url: str | None
    created_at: datetime
