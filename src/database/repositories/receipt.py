from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.dto.receipt import NewReceiptDTO, NewReceiptItemDTO, ReceiptDTO, ReceiptItemDTO
from src.database.errors import translate_db_errors
from src.database.models import Receipt, ReceiptItem


class SqlAlchemyReceiptRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, data: NewReceiptDTO) -> ReceiptDTO:
        stmt = insert(Receipt).values(**data.model_dump()).returning(Receipt)
        with translate_db_errors():
            receipt = (await self._session.execute(stmt)).scalar_one()
        return ReceiptDTO.model_validate(receipt)

    async def get(self, receipt_id: int) -> ReceiptDTO | None:
        receipt = await self._session.get(Receipt, receipt_id)
        return ReceiptDTO.model_validate(receipt) if receipt else None


class SqlAlchemyReceiptItemRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, data: NewReceiptItemDTO) -> ReceiptItemDTO:
        stmt = insert(ReceiptItem).values(**data.model_dump()).returning(ReceiptItem)
        with translate_db_errors():
            item = (await self._session.execute(stmt)).scalar_one()
        return ReceiptItemDTO.model_validate(item)

    async def get(self, item_id: int) -> ReceiptItemDTO | None:
        item = await self._session.get(ReceiptItem, item_id)
        return ReceiptItemDTO.model_validate(item) if item else None
