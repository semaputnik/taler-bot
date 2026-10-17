from aiogram import Dispatcher
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from fluentogram import TranslatorRunner

from src.bot.keyboards.reparse import ReparseCallback
from src.services.container import Services
from src.services.results import CurrentUser


async def reparse(
    message: Message, user: CurrentUser, services: Services, i18n: TranslatorRunner
) -> None:
    summary = await services.receipts.reparse_candidates(user.id)
    if not (summary.failed_count or summary.outdated_count):
        await message.answer(i18n.get("reparse-none"))
        return
    buttons: list[InlineKeyboardButton] = []
    if summary.failed_count:
        buttons.append(
            InlineKeyboardButton(
                text=i18n.get("button-reparse-failed", count=summary.failed_count),
                callback_data=ReparseCallback(reason="failed").pack(),
            )
        )
    if summary.outdated_count:
        buttons.append(
            InlineKeyboardButton(
                text=i18n.get("button-reparse-outdated", count=summary.outdated_count),
                callback_data=ReparseCallback(reason="outdated").pack(),
            )
        )
    text = i18n.get(
        "reparse-summary",
        failed=summary.failed_count,
        outdated=summary.outdated_count,
        version=summary.parser_version,
    )
    await message.answer(
        text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[b] for b in buttons])
    )


def register_reparse(dp: Dispatcher) -> None:
    dp.message.register(reparse, Command("reparse"))
