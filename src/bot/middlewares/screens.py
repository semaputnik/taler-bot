from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from src.bot.screens import ScreenRegistry


class ScreensMiddleware(BaseMiddleware):
    """Puts the app's `ScreenRegistry` into handler data as `screens`."""

    def __init__(self, screens: ScreenRegistry) -> None:
        self._screens = screens

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        data["screens"] = self._screens
        return await handler(event, data)
