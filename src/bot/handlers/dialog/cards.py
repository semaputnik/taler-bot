"""The resting keyboard both cards (receipt and expense) share.

A card's buttons are plain callback buttons (`ReceiptCallback`, `ExpenseCallback`), not dialog
buttons: they are not tied to a dialog context, so they work on any card however old and are
handled by the callback handlers in `bot/handlers/callback/cards.py`.
"""

from collections.abc import Callable

from aiogram.types import CallbackQuery, InlineKeyboardMarkup
from aiogram_dialog import DialogManager
from aiogram_dialog.api.internal import RawKeyboard
from aiogram_dialog.api.internal.widgets import MarkupFactory, MarkupVariant
from aiogram_dialog.api.protocols import DialogProtocol
from aiogram_dialog.widgets.kbd.base import Keyboard

# Builds the card's markup from the window data; None for a card without buttons (deleted).
CardMarkup = Callable[[dict, DialogManager], InlineKeyboardMarkup | None]


class CardKeyboard(Keyboard):
    """The card's resting buttons, built by `build` from the window data."""

    def __init__(self, build: CardMarkup) -> None:
        super().__init__()
        self._build = build

    async def _render_keyboard(self, data: dict, manager: DialogManager) -> RawKeyboard:
        markup = self._build(data, manager)
        return markup.inline_keyboard if markup is not None else []

    async def process_callback(
        self, callback: CallbackQuery, dialog: DialogProtocol, manager: DialogManager
    ) -> bool:
        return False


class PlainKeyboardFactory(MarkupFactory):
    """Markup that keeps the buttons' callback data as it is. The default factory prefixes
    every button with the dialog's intent id, which would tie the card's buttons to one dialog
    context: a tap on an older card would then be dropped as outdated instead of reaching the
    card's callback handler."""

    async def render_markup(
        self, data: dict, manager: DialogManager, keyboard: RawKeyboard
    ) -> MarkupVariant:
        return InlineKeyboardMarkup(inline_keyboard=keyboard)
