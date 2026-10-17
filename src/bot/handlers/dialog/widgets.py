from aiogram_dialog import DialogManager
from aiogram_dialog.widgets.common import WhenCondition
from aiogram_dialog.widgets.text import Text


class I18nText(Text):
    """A text from the `.ftl` files by key, in the translator the middleware put in the data."""

    def __init__(self, key: str, when: WhenCondition = None) -> None:
        super().__init__(when=when)
        self.key = key

    async def _render_text(self, data: dict, manager: DialogManager) -> str:
        return manager.middleware_data["i18n"].get(self.key)
