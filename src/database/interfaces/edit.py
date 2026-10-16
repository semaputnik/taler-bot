from typing import Protocol

from src.database.dto.edit import NewReceiptEditDTO, ReceiptEditDTO


class ReceiptEditRepository(Protocol):
    async def add(self, data: NewReceiptEditDTO) -> ReceiptEditDTO: ...

    async def get(self, edit_id: int) -> ReceiptEditDTO | None: ...
