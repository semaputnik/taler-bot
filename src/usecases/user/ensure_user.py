from pydantic import BaseModel

from src.database.dto.user import NewUserDTO, UserDTO
from src.database.interfaces.uow import UnitOfWorkFactory


class EnsureUserInput(BaseModel):
    telegram_id: int
    username: str | None
    first_name: str | None


class EnsureUser:
    """Create the user on first contact (not allowed), refresh names, return the user."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def __call__(self, data: EnsureUserInput) -> UserDTO:
        async with self._uow_factory() as uow:
            user = await uow.users.upsert(
                NewUserDTO(id=data.telegram_id, username=data.username, first_name=data.first_name)
            )
            await uow.commit()
        return user
