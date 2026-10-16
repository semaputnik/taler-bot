from types import TracebackType
from typing import Protocol, Self

from src.database.interfaces.user import UserRepository


class UnitOfWork(Protocol):
    """One transaction. Nothing is persisted unless `commit()` is called."""

    users: UserRepository

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
