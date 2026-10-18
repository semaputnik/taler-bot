"""Taps on the /reparse message: start the bulk re-read in the background."""

import logging
from typing import Literal

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery
from aiogram.utils.chat_action import ChatActionSender
from fluentogram import TranslatorRunner

from src.bot.handlers.parse_task import TYPING_INTERVAL, send_reply
from src.bot.handlers.screens import screen_of
from src.bot.keyboards.reparse import ReparseCallback
from src.bot.screens import ScreenRegistry
from src.bot.tasks import TaskRegistry
from src.services.container import Services
from src.services.results import CurrentUser

logger = logging.getLogger(__name__)

BULK_LIMIT = 50  # receipts one run reads; the rest wait for the next /reparse


def task_name(user_id: int) -> str:
    return f"reparse-{user_id}"


async def _show_progress(bot: Bot, chat_id: int, message_id: int, text: str) -> None:
    """Replace the buttons with the progress line. A Telegram failure is logged, never raised."""
    try:
        await bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=None)
    except TelegramAPIError:
        logger.warning("Could not edit the /reparse message %s", message_id, exc_info=True)


async def _run(
    bot: Bot,
    chat_id: int,
    message_id: int,
    user_id: int,
    reason: Literal["failed", "outdated"],
    count: int,
    services: Services,
    i18n: TranslatorRunner,
) -> None:
    """Show the progress, read the receipts one after the other, then report. Only
    cancellation leaves it."""
    await _show_progress(bot, chat_id, message_id, i18n.get("reparse-progress", count=count))
    try:
        async with ChatActionSender.typing(bot=bot, chat_id=chat_id, interval=TYPING_INTERVAL):
            result = await services.receipts.reparse_many(user_id, reason, limit=BULK_LIMIT)
    except Exception:
        logger.exception("Bulk re-parse (%s) failed for user %s", reason, user_id)
        return
    text = i18n.get(
        "reparse-done", total=result.ok + result.failed, ok=result.ok, failed=result.failed
    )
    await send_reply(bot, chat_id, message_id, text)


async def start_reparse(
    query: CallbackQuery,
    callback_data: ReparseCallback,
    user: CurrentUser,
    services: Services,
    tasks: TaskRegistry,
    i18n: TranslatorRunner,
    bot: Bot,
    screens: ScreenRegistry,
) -> None:
    summary = await services.receipts.reparse_candidates(user.id)
    # No await between this check and the spawn, so two quick taps cannot both start a run.
    if tasks.is_running(task_name(user.id)):
        await query.answer(i18n.get("reparse-running"), show_alert=True)
        return
    message = query.message
    if message is not None:
        # The question becomes the progress line and then stays: it is no longer a screen.
        await screens.forget(screen_of(message))
        count = summary.failed_count if callback_data.reason == "failed" else summary.outdated_count
        tasks.spawn(
            _run(
                bot,
                message.chat.id,
                message.message_id,
                user.id,
                callback_data.reason,
                min(count, BULK_LIMIT),
                services,
                i18n,
            ),
            name=task_name(user.id),
        )
    await query.answer()


def register_reparse_callbacks(dp: Dispatcher) -> None:
    dp.callback_query.register(start_reparse, ReparseCallback.filter())
