"""Background tasks of the bot: referenced while they run, errors logged, cancelled on exit."""

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

logger = logging.getLogger(__name__)


class TaskRegistry:
    """The event loop keeps only weak references to tasks, so the registry holds them."""

    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[Any]] = set()

    def spawn(self, coro: Coroutine[Any, Any, Any], *, name: str) -> asyncio.Task[Any]:
        task = asyncio.create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._done)
        return task

    def is_running(self, name: str) -> bool:
        """True while a task spawned under `name` has not finished."""
        return any(task.get_name() == name and not task.done() for task in self._tasks)

    def _done(self, task: asyncio.Task[Any]) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            logger.error("Background task %s failed", task.get_name(), exc_info=error)

    async def shutdown(self, timeout: float) -> None:  # noqa: ASYNC109
        """Give pending tasks `timeout` seconds to finish, then cancel the rest and await them."""
        pending = list(self._tasks)
        if not pending:
            return
        _, still_running = await asyncio.wait(pending, timeout=timeout)
        for task in still_running:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    async def drain(self) -> None:
        """Wait for every pending task, including ones they spawn. For tests."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)
