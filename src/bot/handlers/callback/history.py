"""Taps on the history message: month, store filter and page. The message is edited in place."""

import logging

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup
from fluentogram import TranslatorRunner

from src.bot.handlers.command.receipts import send_history
from src.bot.keyboards.history import HistoryAction, HistoryCallback
from src.bot.views import history as view
from src.services.container import Services
from src.services.results import CurrentUser

logger = logging.getLogger(__name__)

_IGNORED = ("message is not modified", "message to edit not found")


async def show_history(
    query: CallbackQuery,
    callback_data: HistoryCallback,
    user: CurrentUser,
    services: Services,
    i18n: TranslatorRunner,
    bot: Bot,
) -> None:
    await query.answer()
    if query.message is None:
        return
    if callback_data.action is HistoryAction.OPEN:
        # The /start button: the greeting stays, the list is a new message.
        shown = callback_data.model_copy(update={"action": HistoryAction.SHOW})
        await send_history(query.message, shown, user, services, i18n)
        return
    page = await services.expenses.history(
        user.id,
        callback_data.year,
        callback_data.month,
        payee_id=callback_data.store_id or None,
        page=callback_data.page,
    )
    text = view.show_text(page, i18n)
    markup: InlineKeyboardMarkup
    if callback_data.action is HistoryAction.STORES:
        text = view.stores_text(page, i18n)
        markup = view.stores_keyboard(page, callback_data, i18n)
    else:
        markup = view.show_keyboard(page, callback_data, i18n)
    try:
        await bot.edit_message_text(
            text,
            chat_id=query.message.chat.id,
            message_id=query.message.message_id,
            reply_markup=markup,
        )
    except TelegramBadRequest as error:
        if not any(marker in str(error) for marker in _IGNORED):
            raise


def register_history_callbacks(dp: Dispatcher) -> None:
    dp.callback_query.register(show_history, HistoryCallback.filter())
