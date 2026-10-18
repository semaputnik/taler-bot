"""The background task that deletes expired screens."""

import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.storage.base import BaseStorage
from aiogram.fsm.storage.memory import SimpleEventIsolation
from aiogram_dialog.api.entities import ShowMode
from aiogram_dialog.api.protocols import BgManagerFactory
from aiogram_dialog.context.storage import StorageProxy

from src.bot.screens import Screen, ScreenKind, ScreenRegistry

logger = logging.getLogger(__name__)

SWEEPER_TASK_NAME = "screens-sweeper"


class ScreenSweeper:
    def __init__(self, bot: Bot, screens: ScreenRegistry, *, interval_seconds: float) -> None:
        self._bot = bot
        self._screens = screens
        self._interval = interval_seconds
        self._dialogs: BgManagerFactory | None = None
        self._storage: BaseStorage | None = None

    def use_dialogs(self, dialogs: BgManagerFactory, storage: BaseStorage) -> None:
        self._dialogs = dialogs
        self._storage = storage

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
        if screen.kind is ScreenKind.ENTRY:
            await self._close_entry(screen)
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

    async def _close_entry(self, screen: Screen) -> None:
        """The entry runs alone on a reset stack, so finishing the chat's dialog closes it. In a
        private chat the user id is the chat id. Nothing happens unless that dialog is still the
        one showing this message: the user may have moved on to a card or another entry."""
        if self._dialogs is None or self._storage is None:
            return
        try:
            if not await self._shows(screen):
                return
            manager = self._dialogs.bg(self._bot, user_id=screen.chat_id, chat_id=screen.chat_id)
            await manager.done(show_mode=ShowMode.NO_UPDATE)
        except Exception:
            logger.exception("Could not close the entry dialog of chat %s", screen.chat_id)

    async def _shows(self, screen: Screen) -> bool:
        proxy = StorageProxy(
            self._storage,
            SimpleEventIsolation(),
            user_id=screen.chat_id,
            chat_id=screen.chat_id,
            thread_id=None,
            business_connection_id=None,
            bot=self._bot,
            state_groups={},
        )
        try:
            stack = await proxy.load_stack()
        finally:
            await proxy.unlock()
        return not stack.empty() and stack.last_message_id == screen.message_id
