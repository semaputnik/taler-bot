from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from fluentogram import TranslatorHub

from src.bot.i18n import DEFAULT_LOCALE


class I18nMiddleware(BaseMiddleware):
    """Puts the translator into handler data as `i18n`. Always `en` for now."""

    def __init__(self, hub: TranslatorHub) -> None:
        self._hub = hub

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        data["i18n"] = self._hub.get_translator_by_locale(DEFAULT_LOCALE)
        return await handler(event, data)
