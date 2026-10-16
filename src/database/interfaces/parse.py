from typing import Protocol

from src.database.dto.parse import NewReceiptParseDTO, ReceiptParseDTO


class ReceiptParseRepository(Protocol):
    async def add(self, data: NewReceiptParseDTO) -> ReceiptParseDTO: ...

    async def get(self, parse_id: int) -> ReceiptParseDTO | None: ...

    async def delete(self, parse_id: int) -> None:
        """Remove the parse; receipts that pointed at it keep existing and lose the pointer."""
        ...
