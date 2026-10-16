from typing import Protocol

from src.database.dto.user import NewUserDTO, UserDTO


class UserRepository(Protocol):
    async def get(self, user_id: int) -> UserDTO | None: ...

    async def upsert(self, data: NewUserDTO) -> UserDTO:
        """Create the user (not allowed), or refresh username and first name."""
        ...

    async def set_allowed(self, user_id: int, allowed: bool) -> UserDTO | None: ...
