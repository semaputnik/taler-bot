from dataclasses import dataclass
from typing import Self

from src.database.interfaces.uow import UnitOfWorkFactory
from src.usecases.user.ensure_user import EnsureUser


@dataclass(frozen=True)
class UseCases:
    """All use cases, built once by `App`; a middleware puts it into handler data."""

    ensure_user: EnsureUser

    @classmethod
    def build(cls, uow_factory: UnitOfWorkFactory) -> Self:
        return cls(ensure_user=EnsureUser(uow_factory))
