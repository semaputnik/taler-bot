from pydantic import BaseModel, ConfigDict


class NewUserDTO(BaseModel):
    """What Telegram tells us about a user."""

    id: int
    username: str | None
    first_name: str | None


class UserDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: int
    username: str | None
    first_name: str | None
    is_allowed: bool
    is_admin: bool
    timezone: str
    default_currency: str
