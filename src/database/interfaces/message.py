from typing import Protocol

from src.database.dto.message import NewReceiptMessageDTO, ReceiptMessageDTO


class ReceiptMessageRepository(Protocol):
    async def add(self, data: NewReceiptMessageDTO) -> ReceiptMessageDTO: ...

    async def get(self, user_id: int, message_id: int) -> ReceiptMessageDTO | None: ...
