from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.dto.issue import NewReceiptIssueDTO, ReceiptIssueDTO
from src.database.errors import translate_db_errors
from src.database.models import ReceiptIssue


class SqlAlchemyReceiptIssueRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, data: NewReceiptIssueDTO) -> ReceiptIssueDTO:
        stmt = insert(ReceiptIssue).values(**data.model_dump()).returning(ReceiptIssue)
        with translate_db_errors():
            row = (await self._session.execute(stmt)).scalar_one()
        return ReceiptIssueDTO.model_validate(row)

    async def get(self, issue_id: int) -> ReceiptIssueDTO | None:
        row = await self._session.get(ReceiptIssue, issue_id)
        return ReceiptIssueDTO.model_validate(row) if row else None
