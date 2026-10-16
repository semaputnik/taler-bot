from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from src.bot.usecases import UseCases


class UseCasesMiddleware(BaseMiddleware):
    """Puts the use-case container into handler data as `usecases`."""

    def __init__(self, usecases: UseCases) -> None:
        self._usecases = usecases

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        data["usecases"] = self._usecases
        return await handler(event, data)
