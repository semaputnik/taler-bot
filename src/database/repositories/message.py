from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.dto.message import NewReceiptMessageDTO, ReceiptMessageDTO
from src.database.models import ReceiptMessage


class SqlAlchemyReceiptMessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, data: NewReceiptMessageDTO) -> ReceiptMessageDTO:
        stmt = insert(ReceiptMessage).values(**data.model_dump()).returning(ReceiptMessage)
        row = (await self._session.execute(stmt)).scalar_one()
        return ReceiptMessageDTO.model_validate(row)

    async def get(self, user_id: int, message_id: int) -> ReceiptMessageDTO | None:
        row = await self._session.get(ReceiptMessage, (user_id, message_id))
        return ReceiptMessageDTO.model_validate(row) if row else None
