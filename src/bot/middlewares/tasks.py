from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from src.bot.tasks import TaskRegistry


class TasksMiddleware(BaseMiddleware):
    """Puts the app's `TaskRegistry` into handler data as `tasks`."""

    def __init__(self, tasks: TaskRegistry) -> None:
        self._tasks = tasks

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        data["tasks"] = self._tasks
        return await handler(event, data)
