from sqlalchemy import delete, insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.dto.parse import NewReceiptParseDTO, ReceiptParseDTO
from src.database.errors import translate_db_errors
from src.database.models import ReceiptParse


class SqlAlchemyReceiptParseRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, data: NewReceiptParseDTO) -> ReceiptParseDTO:
        stmt = insert(ReceiptParse).values(**data.model_dump()).returning(ReceiptParse)
        with translate_db_errors():
            row = (await self._session.execute(stmt)).scalar_one()
        return ReceiptParseDTO.model_validate(row)

    async def get(self, parse_id: int) -> ReceiptParseDTO | None:
        row = await self._session.get(ReceiptParse, parse_id)
        return ReceiptParseDTO.model_validate(row) if row else None

    async def delete(self, parse_id: int) -> None:
        with translate_db_errors():
            await self._session.execute(delete(ReceiptParse).where(ReceiptParse.id == parse_id))
