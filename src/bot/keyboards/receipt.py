"""The inline keyboard under a receipt's summary, and the callback data its buttons carry."""

from enum import StrEnum

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from fluentogram import TranslatorRunner


class CardWindow(StrEnum):
    """The `ReceiptCard` window a summary button opens."""

    MAIN = "main"
    ITEMS = "items"
    REVIEW = "review"
    CATEGORY = "category"
    TAGS = "tags"
    PHOTO = "photo"
    DELETE_CONFIRM = "delete_confirm"
    REPARSE = "reparse"  # not a window: reads the receipt again, then sends a fresh card
    CLOSE = "close"  # not a window: hides the card's buttons


class ReceiptCallback(CallbackData, prefix="receipt"):
    receipt_id: int
    window: CardWindow


def receipt_keyboard(
    i18n: TranslatorRunner,
    receipt_id: int,
    *,
    item_count: int = 0,
    review_count: int = 0,
    can_reparse: bool = False,
    can_categorise: bool = False,
) -> InlineKeyboardMarkup:
    """Buttons under the parse reply: Items (only when the receipt has items), Review (only when
    issues wait for the user), Category and Tags (only when the receipt has an expense), Photo,
    Delete;
    Re-parse on its own row (only when the receipt can be read again), then Close."""
    reading = [CardWindow.ITEMS] if item_count > 0 else []
    if review_count > 0:
        reading.append(CardWindow.REVIEW)
    expense = [CardWindow.CATEGORY, CardWindow.TAGS] if can_categorise else []
    rest = [CardWindow.PHOTO, CardWindow.DELETE_CONFIRM]

    def button(window: CardWindow) -> InlineKeyboardButton:
        return InlineKeyboardButton(
            text=i18n.get(_BUTTON_KEYS[window], **_button_args(window, review_count)),
            callback_data=ReceiptCallback(receipt_id=receipt_id, window=window).pack(),
        )

    # Two buttons per row (four in one row are unreadable on a phone). Items and Review share
    # a row, Category and Tags always share one, Photo and Delete share one; Re-parse and Close
    # each have their own row.
    rows = [[button(window) for window in group] for group in (reading, expense, rest) if group]
    if can_reparse:
        rows.append([button(CardWindow.REPARSE)])
    rows.append([button(CardWindow.CLOSE)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


_BUTTON_KEYS = {
    CardWindow.ITEMS: "button-items",
    CardWindow.PHOTO: "button-photo",
    CardWindow.DELETE_CONFIRM: "button-delete",
    CardWindow.REVIEW: "button-review",
    CardWindow.CATEGORY: "button-category",
    CardWindow.TAGS: "button-tags",
    CardWindow.REPARSE: "button-reparse",
    CardWindow.CLOSE: "button-close",
}


def _button_args(window: CardWindow, review_count: int) -> dict[str, str]:
    return {"count": str(review_count)} if window is CardWindow.REVIEW else {}
