from types import TracebackType
from typing import Protocol, Self

from src.database.interfaces.catalog import CatalogRepository
from src.database.interfaces.edit import ReceiptEditRepository
from src.database.interfaces.issue import ReceiptIssueRepository
from src.database.interfaces.message import ReceiptMessageRepository
from src.database.interfaces.parse import ReceiptParseRepository
from src.database.interfaces.photo import ReceiptPhotoRepository
from src.database.interfaces.receipt import ReceiptItemRepository, ReceiptRepository
from src.database.interfaces.user import UserRepository


class UnitOfWork(Protocol):
    """One transaction. Nothing is persisted unless `commit()` is called."""

    users: UserRepository
    catalog: CatalogRepository
    receipts: ReceiptRepository
    items: ReceiptItemRepository
    photos: ReceiptPhotoRepository
    parses: ReceiptParseRepository
    issues: ReceiptIssueRepository
    edits: ReceiptEditRepository
    messages: ReceiptMessageRepository

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...


class UnitOfWorkFactory(Protocol):
    def __call__(self) -> UnitOfWork: ...
