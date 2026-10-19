"""Expiring screens: a screen is a message opened by a command or a menu button.

The registry knows ids and a kind, never aiogram objects. It tracks a screen with a due time
(now + TTL), moves the time on a tap (`touch`, only for a tracked screen), drops it (`forget`)
and hands out the screens whose time has come (`due`). Where the times live is a `ScreenStore`.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class ScreenKind(StrEnum):
    PLAIN = "plain"  # a message with plain callback buttons
    ENTRY = "entry"  # the message of a manual entry dialog (closing the dialog: a later ticket)


@dataclass(frozen=True)
class Screen:
    chat_id: int
    message_id: int
    kind: ScreenKind = ScreenKind.PLAIN


class ScreenStore(Protocol):
    async def add(self, screen: Screen, due_at: float) -> None:
        """Track the screen, or move the time of one already tracked."""
        ...

    async def update(self, screen: Screen, due_at: float) -> None:
        """Move the time of a tracked screen; an untracked one stays untracked."""
        ...

    async def remove(self, screen: Screen) -> None: ...

    async def tracked(self, screen: Screen) -> bool: ...

    async def due(self, now: float) -> list[Screen]:
        """Remove and return the screens due at `now`, the earliest first."""
        ...


class MemoryScreenStore:
    def __init__(self) -> None:
        self._due: dict[Screen, float] = {}

    async def add(self, screen: Screen, due_at: float) -> None:
        self._due[screen] = due_at

    async def update(self, screen: Screen, due_at: float) -> None:
        if screen in self._due:
            self._due[screen] = due_at

    async def remove(self, screen: Screen) -> None:
        self._due.pop(screen, None)

    async def tracked(self, screen: Screen) -> bool:
        return screen in self._due

    async def due(self, now: float) -> list[Screen]:
        ready = sorted((s for s, at in self._due.items() if at <= now), key=self._due.__getitem__)
        for screen in ready:
            del self._due[screen]
        return ready


class ScreenRegistry:
    """With a TTL of 0 the registry is off: nothing is tracked and nothing is ever due."""

    def __init__(
        self,
        store: ScreenStore,
        *,
        ttl_minutes: int,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._store = store
        self._ttl = ttl_minutes * 60
        self._clock = clock

    @property
    def enabled(self) -> bool:
        return self._ttl > 0

    def now(self) -> float:
        return self._clock()

    async def track(self, screen: Screen) -> None:
        if self.enabled:
            await self._store.add(screen, self._clock() + self._ttl)

    async def touch(self, screen: Screen) -> None:
        if self.enabled:
            await self._store.update(screen, self._clock() + self._ttl)

    async def forget(self, screen: Screen) -> None:
        if self.enabled:
            await self._store.remove(screen)

    async def move(self, old: Screen, new: Screen) -> None:
        """The message was replaced: if `old` was tracked, `new` takes its place with a full TTL."""
        if self.enabled and await self._store.tracked(old):
            await self._store.remove(old)
            await self._store.add(new, self._clock() + self._ttl)

    async def due(self, now: float) -> list[Screen]:
        return await self._store.due(now) if self.enabled else []
