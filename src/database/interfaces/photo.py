from typing import Protocol

from src.database.dto.photo import NewReceiptPhotoDTO, ReceiptPhotoDTO


class ReceiptPhotoRepository(Protocol):
    async def add(self, data: NewReceiptPhotoDTO) -> ReceiptPhotoDTO: ...

    async def get(self, photo_id: int) -> ReceiptPhotoDTO | None: ...
