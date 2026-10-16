from sqlalchemy import delete, func, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.dto.user import NewUserDTO, UserDTO
from src.database.errors import translate_db_errors
from src.database.models import User


class SqlAlchemyUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: int) -> UserDTO | None:
        user = await self._session.get(User, user_id)
        return UserDTO.model_validate(user) if user else None

    async def upsert(self, data: NewUserDTO) -> UserDTO:
        values = data.model_dump()
        stmt = (
            insert(User)
            .values(**values)
            .on_conflict_do_update(
                index_elements=[User.id],
                set_={
                    "username": data.username,
                    "first_name": data.first_name,
                    "updated_at": func.now(),
                },
            )
            .returning(User)
            .execution_options(populate_existing=True)
        )
        with translate_db_errors():
            user = (await self._session.execute(stmt)).scalar_one()
        return UserDTO.model_validate(user)

    async def set_allowed(self, user_id: int, allowed: bool) -> UserDTO | None:
        stmt = (
            update(User)
            .where(User.id == user_id)
            .values(is_allowed=allowed, updated_at=func.now())
            .returning(User)
            .execution_options(populate_existing=True)
        )
        with translate_db_errors():
            user = (await self._session.execute(stmt)).scalar_one_or_none()
        return UserDTO.model_validate(user) if user else None

    async def delete(self, user_id: int) -> None:
        with translate_db_errors():
            await self._session.execute(delete(User).where(User.id == user_id))
