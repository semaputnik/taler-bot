from dataclasses import dataclass
from typing import Self

from src.database.interfaces.uow import UnitOfWorkFactory
from src.integration.llm import ReceiptParser
from src.integration.storage import PhotoStorage
from src.services.receipt import ReceiptService
from src.services.user import UserService


@dataclass(frozen=True)
class Services:
    """All services, built once by `App`; a middleware puts it into handler data."""

    users: UserService
    receipts: ReceiptService

    @classmethod
    def build(
        cls, uow_factory: UnitOfWorkFactory, *, storage: PhotoStorage, parser: ReceiptParser
    ) -> Self:
        return cls(
            users=UserService(uow_factory),
            receipts=ReceiptService(uow_factory, storage, parser),
        )
