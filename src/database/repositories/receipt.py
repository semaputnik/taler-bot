from sqlalchemy import insert, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.dto.receipt import NewReceiptDTO, NewReceiptItemDTO, ReceiptDTO, ReceiptItemDTO
from src.database.models import Receipt, ReceiptItem


class SqlAlchemyReceiptRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, data: NewReceiptDTO) -> ReceiptDTO:
        stmt = insert(Receipt).values(**data.model_dump()).returning(Receipt)
        receipt = (await self._session.execute(stmt)).scalar_one()
        return ReceiptDTO.model_validate(receipt)

    async def get(self, receipt_id: int) -> ReceiptDTO | None:
        # Refresh a row this session already loaded: bulk updates and DB cascades bypass it.
        receipt = await self._session.get(Receipt, receipt_id, populate_existing=True)
        return ReceiptDTO.model_validate(receipt) if receipt else None

    async def set_current_parse(self, receipt_id: int, parse_id: int | None) -> None:
        stmt = update(Receipt).where(Receipt.id == receipt_id).values(current_parse_id=parse_id)
        await self._session.execute(stmt)


class SqlAlchemyReceiptItemRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, data: NewReceiptItemDTO) -> ReceiptItemDTO:
        stmt = insert(ReceiptItem).values(**data.model_dump()).returning(ReceiptItem)
        item = (await self._session.execute(stmt)).scalar_one()
        return ReceiptItemDTO.model_validate(item)

    async def get(self, item_id: int) -> ReceiptItemDTO | None:
        item = await self._session.get(ReceiptItem, item_id)
        return ReceiptItemDTO.model_validate(item) if item else None
