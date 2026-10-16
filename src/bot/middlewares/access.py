from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from aiogram.types import User as TelegramUser


class AccessMiddleware(BaseMiddleware):
    """Outer middleware on every update.

    Records the sender (creating them as not allowed on first contact) and stops the
    update silently unless `users.is_allowed`. Needs `services` in data.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        sender: TelegramUser | None = data.get("event_from_user")
        if sender is None:
            return None
        user = await data["services"].users.ensure(
            telegram_id=sender.id, username=sender.username, first_name=sender.first_name
        )
        if not user.is_allowed:
            return None
        data["user"] = user
        return await handler(event, data)
