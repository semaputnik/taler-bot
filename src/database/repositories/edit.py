from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.dto.edit import NewReceiptEditDTO, ReceiptEditDTO
from src.database.errors import translate_db_errors
from src.database.models import ReceiptEdit


class SqlAlchemyReceiptEditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, data: NewReceiptEditDTO) -> ReceiptEditDTO:
        stmt = insert(ReceiptEdit).values(**data.model_dump()).returning(ReceiptEdit)
        with translate_db_errors():
            row = (await self._session.execute(stmt)).scalar_one()
        return ReceiptEditDTO.model_validate(row)

    async def get(self, edit_id: int) -> ReceiptEditDTO | None:
        row = await self._session.get(ReceiptEdit, edit_id)
        return ReceiptEditDTO.model_validate(row) if row else None
