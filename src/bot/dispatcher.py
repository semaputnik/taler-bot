from aiogram import Dispatcher
from aiogram.fsm.storage.base import BaseStorage
from aiogram_dialog import setup_dialogs
from fluentogram import TranslatorHub

from src.bot.handlers.setup import register_handlers
from src.bot.middlewares.access import AccessMiddleware
from src.bot.middlewares.i18n import I18nMiddleware
from src.bot.middlewares.usecases import UseCasesMiddleware
from src.usecases.container import UseCases


def create_dispatcher(
    *, storage: BaseStorage, usecases: UseCases, translator_hub: TranslatorHub
) -> Dispatcher:
    dp = Dispatcher(storage=storage)
    # Order matters: access needs `usecases`; aiogram sets `event_from_user` before all of them.
    dp.update.outer_middleware(UseCasesMiddleware(usecases))
    dp.update.outer_middleware(AccessMiddleware())
    dp.update.outer_middleware(I18nMiddleware(translator_hub))
    register_handlers(dp)
    setup_dialogs(dp)
    return dp
