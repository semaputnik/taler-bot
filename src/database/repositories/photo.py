from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.dto.photo import NewReceiptPhotoDTO, ReceiptPhotoDTO
from src.database.models import ReceiptPhoto


class SqlAlchemyReceiptPhotoRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, data: NewReceiptPhotoDTO) -> ReceiptPhotoDTO:
        stmt = insert(ReceiptPhoto).values(**data.model_dump()).returning(ReceiptPhoto)
        row = (await self._session.execute(stmt)).scalar_one()
        return ReceiptPhotoDTO.model_validate(row)

    async def get(self, photo_id: int) -> ReceiptPhotoDTO | None:
        row = await self._session.get(ReceiptPhoto, photo_id)
        return ReceiptPhotoDTO.model_validate(row) if row else None
