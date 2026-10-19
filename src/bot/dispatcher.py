from aiogram import Dispatcher
from aiogram.fsm.storage.base import BaseStorage
from aiogram_dialog import setup_dialogs
from aiogram_dialog.context.media_storage import MediaIdStorage
from fluentogram import TranslatorHub

from src.bot.handlers.dialog.media import StoredPhotoMessageManager
from src.bot.handlers.dialog.tracking import TrackingManagerFactory
from src.bot.handlers.setup import register_handlers
from src.bot.middlewares.access import AccessMiddleware
from src.bot.middlewares.i18n import I18nMiddleware
from src.bot.middlewares.screens import ScreensMiddleware
from src.bot.middlewares.services import ServicesMiddleware
from src.bot.middlewares.tasks import TasksMiddleware
from src.bot.screens import ScreenRegistry
from src.bot.sweeper import ScreenSweeper
from src.bot.tasks import TaskRegistry
from src.services.container import Services


def create_dispatcher(
    *,
    storage: BaseStorage,
    services: Services,
    translator_hub: TranslatorHub,
    tasks: TaskRegistry,
    screens: ScreenRegistry,
    sweeper: ScreenSweeper | None = None,
) -> Dispatcher:
    dp = Dispatcher(storage=storage)
    # Order matters: access needs `services`; aiogram sets `event_from_user` before all of them.
    dp.update.outer_middleware(ServicesMiddleware(services))
    dp.update.outer_middleware(TasksMiddleware(tasks))
    dp.update.outer_middleware(ScreensMiddleware(screens))
    dp.update.outer_middleware(AccessMiddleware())
    dp.update.outer_middleware(I18nMiddleware(translator_hub))
    register_handlers(dp)
    dialogs = setup_dialogs(
        dp,
        dialog_manager_factory=TrackingManagerFactory(
            message_manager=StoredPhotoMessageManager(screens),
            media_id_storage=MediaIdStorage(),
            getter=None,
        ),
    )
    if sweeper is not None:
        sweeper.use_dialogs(
            dialogs, storage
        )  # it closes the entry dialog of a chat whose entry expired
    return dp
