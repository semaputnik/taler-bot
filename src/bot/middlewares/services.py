from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from src.services.container import Services


class ServicesMiddleware(BaseMiddleware):
    """Puts the service container into handler data as `services`."""

    def __init__(self, services: Services) -> None:
        self._services = services

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        data["services"] = self._services
        return await handler(event, data)
