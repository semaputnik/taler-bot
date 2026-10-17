"""Taps on the stats message: the period and the kind. The message is edited in place."""

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery
from fluentogram import TranslatorRunner

from src.bot.handlers.command.stats import send_stats
from src.bot.keyboards.stats import StatsAction, StatsCallback
from src.bot.views import stats as view
from src.services.container import Services
from src.services.results import CurrentUser

_IGNORED = ("message is not modified", "message to edit not found")


async def show_stats(
    query: CallbackQuery,
    callback_data: StatsCallback,
    user: CurrentUser,
    services: Services,
    i18n: TranslatorRunner,
    bot: Bot,
) -> None:
    await query.answer()
    if query.message is None:
        return
    if callback_data.action is StatsAction.OPEN:
        # The /start button: the greeting stays, the stats are a new message.
        shown = callback_data.model_copy(update={"action": StatsAction.SHOW})
        await send_stats(query.message, shown, user, services, i18n)
        return
    report = await services.expenses.spending(
        user.id, callback_data.kind.value, callback_data.anchor
    )
    try:
        await bot.edit_message_text(
            view.show_text(report, i18n),
            chat_id=query.message.chat.id,
            message_id=query.message.message_id,
            reply_markup=view.show_keyboard(report, i18n),
        )
    except TelegramBadRequest as error:
        if not any(marker in str(error) for marker in _IGNORED):
            raise


def register_stats_callbacks(dp: Dispatcher) -> None:
    dp.callback_query.register(show_stats, StatsCallback.filter())
