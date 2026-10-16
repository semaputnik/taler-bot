from sqlalchemy import CHAR, text
from sqlalchemy.orm import Mapped, mapped_column

from src.database.models.base import Base, Timestamps


class User(Timestamps, Base):
    """A Telegram user. Replaces n8n `telegram_whitelist`; `is_allowed` is the whitelist."""

    __tablename__ = "users"

    # Telegram user id, not a generated key.
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    username: Mapped[str | None]
    first_name: Mapped[str | None]
    is_allowed: Mapped[bool] = mapped_column(server_default=text("false"))
    is_admin: Mapped[bool] = mapped_column(server_default=text("false"))
    timezone: Mapped[str] = mapped_column(server_default="Europe/Madrid")
    default_currency: Mapped[str] = mapped_column(CHAR(3), server_default="EUR")
