from src.database.dto.user import NewUserDTO
from src.database.interfaces.uow import UnitOfWorkFactory
from src.exception import UserNotFound
from src.services.results import CurrentUser


class UserService:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def ensure(
        self, telegram_id: int, username: str | None, first_name: str | None
    ) -> CurrentUser:
        """Create the user on first contact (not allowed), refresh names, return the user."""
        async with self._uow_factory() as uow:
            user = await uow.users.upsert(
                NewUserDTO(id=telegram_id, username=username, first_name=first_name)
            )
            await uow.commit()
        return CurrentUser.model_validate(user)

    async def allow(self, user_id: int) -> CurrentUser:
        async with self._uow_factory() as uow:
            user = await uow.users.set_allowed(user_id, True)
            if user is None:
                raise UserNotFound(user_id)
            await uow.commit()
        return CurrentUser.model_validate(user)
