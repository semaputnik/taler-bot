from datetime import datetime

from pydantic import BaseModel, ConfigDict


class NewReceiptMessageDTO(BaseModel):
    user_id: int
    message_id: int
    receipt_id: int


class ReceiptMessageDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    user_id: int
    message_id: int
    receipt_id: int
    created_at: datetime
