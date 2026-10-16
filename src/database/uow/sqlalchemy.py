from collections.abc import Callable
from types import TracebackType
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession

from src.database.errors import translate_db_errors
from src.database.repositories.user import SqlAlchemyUserRepository


class SqlAlchemyUnitOfWork:
    """Opens one session per `async with`; rolls back unless `commit()` was awaited.

    Add new repositories in `__aenter__`, next to `users`.
    """

    def __init__(self, session_factory: Callable[[], AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None

    async def __aenter__(self) -> Self:
        self._session = self._session_factory()
        self.users = SqlAlchemyUserRepository(self._session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        assert self._session is not None
        try:
            await self._session.rollback()  # no-op after a commit
        finally:
            await self._session.close()
            self._session = None

    async def commit(self) -> None:
        assert self._session is not None
        with translate_db_errors():
            await self._session.commit()
