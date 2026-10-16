from typing import Protocol

from src.database.dto.receipt import NewReceiptDTO, NewReceiptItemDTO, ReceiptDTO, ReceiptItemDTO


class ReceiptRepository(Protocol):
    async def add(self, data: NewReceiptDTO) -> ReceiptDTO: ...

    async def get(self, receipt_id: int) -> ReceiptDTO | None: ...


class ReceiptItemRepository(Protocol):
    async def add(self, data: NewReceiptItemDTO) -> ReceiptItemDTO: ...

    async def get(self, item_id: int) -> ReceiptItemDTO | None: ...
