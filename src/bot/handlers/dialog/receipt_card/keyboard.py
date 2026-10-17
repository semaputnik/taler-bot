from aiogram.types import CallbackQuery, InlineKeyboardMarkup
from aiogram_dialog import DialogManager
from aiogram_dialog.api.internal import RawKeyboard
from aiogram_dialog.api.internal.widgets import MarkupFactory, MarkupVariant
from aiogram_dialog.api.protocols import DialogProtocol
from aiogram_dialog.widgets.kbd.base import Keyboard

from src.bot.handlers.dialog.receipt_card.common import DialogDataKeys, PreviewDataKeys
from src.bot.keyboards.receipt import receipt_keyboard


class CardKeyboard(Keyboard):
    """The card's resting buttons as plain callback buttons (`ReceiptCallback`).

    They are not dialog buttons, so they keep working on any card however old, and are
    handled by `open_card`, which edits the current card or sends a fresh one.
    """

    async def _render_keyboard(self, data: dict, manager: DialogManager) -> RawKeyboard:
        if not data[PreviewDataKeys.CAN_DELETE]:  # a deleted card has no buttons
            return []
        markup = receipt_keyboard(
            manager.middleware_data["i18n"],
            manager.dialog_data[DialogDataKeys.RECEIPT_ID],
            item_count=1 if data[PreviewDataKeys.HAS_ITEMS] else 0,
            review_count=data[PreviewDataKeys.REVIEW_COUNT],
            can_reparse=data[PreviewDataKeys.CAN_REPARSE],
        )
        return markup.inline_keyboard

    async def process_callback(
        self, callback: CallbackQuery, dialog: DialogProtocol, manager: DialogManager
    ) -> bool:
        return False


class PlainKeyboardFactory(MarkupFactory):
    """Markup that keeps the buttons' callback data as it is. The default factory prefixes
    every button with the dialog's intent id, which would tie the card's buttons to one dialog
    context: a tap on an older card would then be dropped as outdated instead of reaching
    `open_card`."""

    async def render_markup(
        self, data: dict, manager: DialogManager, keyboard: RawKeyboard
    ) -> MarkupVariant:
        return InlineKeyboardMarkup(inline_keyboard=keyboard)
