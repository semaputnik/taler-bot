from aiogram_dialog import DialogManager
from aiogram_dialog.widgets.common import WhenCondition
from aiogram_dialog.widgets.text import Text


class I18nText(Text):
    """A text from the `.ftl` files by key, in the translator the middleware put in the data."""

    def __init__(self, key: str, when: WhenCondition = None, **data_args: str) -> None:
        """`data_args` maps a text variable to the key of the window data holding its value."""
        super().__init__(when=when)
        self.key = key
        self.data_args = data_args

    async def _render_text(self, data: dict, manager: DialogManager) -> str:
        args = {name: str(data[data_key]) for name, data_key in self.data_args.items()}
        return manager.middleware_data["i18n"].get(self.key, **args)
