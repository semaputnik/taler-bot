"""The background task that deletes expired screens."""

import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from src.bot.screens import Screen, ScreenRegistry

logger = logging.getLogger(__name__)

SWEEPER_TASK_NAME = "screens-sweeper"


class ScreenSweeper:
    def __init__(self, bot: Bot, screens: ScreenRegistry, *, interval_seconds: float) -> None:
        self._bot = bot
        self._screens = screens
        self._interval = interval_seconds

    async def run(self) -> None:
        """Sweep every interval until cancelled; an error in a sweep never ends the loop."""
        while True:
            await asyncio.sleep(self._interval)
            try:
                await self.sweep_once(self._screens.now())
            except Exception:
                logger.exception("Screen sweep failed")

    async def sweep_once(self, now: float) -> None:
        for screen in await self._screens.due(now):
            await self._expire(screen)

    async def _expire(self, screen: Screen) -> None:
        try:
            await self._bot.delete_message(screen.chat_id, screen.message_id)
            return
        except TelegramAPIError:
            pass  # too old to delete, or already gone: at least remove the buttons
        try:
            await self._bot.edit_message_reply_markup(
                chat_id=screen.chat_id, message_id=screen.message_id, reply_markup=None
            )
        except TelegramAPIError as error:
            logger.warning("Could not expire screen %s: %s", screen, error)
