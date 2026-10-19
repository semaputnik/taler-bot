"""A dialog manager that tells the message manager which dialog is being shown.

aiogram-dialog's `MessageManager.show_message` gets only the rendered message, not the dialog it
belongs to. `TrackingManager.show` publishes the state group in `showing_group` for the duration
of the call, so the message manager can recognise the manual entry by its state group.
"""

from aiogram_dialog.manager.manager import ManagerImpl
from aiogram_dialog.manager.manager_factory import DefaultManagerFactory

from src.bot.handlers.dialog.media import showing_group


class TrackingManager(ManagerImpl):
    async def show(self, show_mode=None) -> None:
        token = showing_group.set(self.current_context().state.group)
        try:
            await super().show(show_mode)
        finally:
            showing_group.reset(token)


class TrackingManagerFactory(DefaultManagerFactory):
    def __call__(self, event, data, registry, router):
        return TrackingManager(
            event=event,
            data=data,
            message_manager=self.message_manager,
            media_id_storage=self.media_id_storage,
            registry=registry,
            router=router,
            getter=self.getter,
        )
