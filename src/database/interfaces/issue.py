from typing import Protocol

from src.database.dto.issue import NewReceiptIssueDTO, ReceiptIssueDTO


class ReceiptIssueRepository(Protocol):
    async def add(self, data: NewReceiptIssueDTO) -> ReceiptIssueDTO: ...

    async def get(self, issue_id: int) -> ReceiptIssueDTO | None: ...
