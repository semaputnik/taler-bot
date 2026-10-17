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
    PHOTO = "photo"
    DELETE_CONFIRM = "delete_confirm"


class ReceiptCallback(CallbackData, prefix="receipt"):
    receipt_id: int
    window: CardWindow


def receipt_keyboard(
    i18n: TranslatorRunner, receipt_id: int, *, item_count: int = 0, review_count: int = 0
) -> InlineKeyboardMarkup:
    """Buttons under the parse reply: Items (only when the receipt has items), Review (only when
    issues wait for the user), Photo, Delete."""
    windows = [CardWindow.ITEMS] if item_count > 0 else []
    if review_count > 0:
        windows.append(CardWindow.REVIEW)
    windows += [CardWindow.PHOTO, CardWindow.DELETE_CONFIRM]
    buttons = [
        InlineKeyboardButton(
            text=i18n.get(_BUTTON_KEYS[window], **_button_args(window, review_count)),
            callback_data=ReceiptCallback(receipt_id=receipt_id, window=window).pack(),
        )
        for window in windows
    ]
    # Two buttons per row: four in one row are unreadable on a phone.
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(inline_keyboard=rows)


_BUTTON_KEYS = {
    CardWindow.ITEMS: "button-items",
    CardWindow.PHOTO: "button-photo",
    CardWindow.DELETE_CONFIRM: "button-delete",
    CardWindow.REVIEW: "button-review",
}


def _button_args(window: CardWindow, review_count: int) -> dict[str, str]:
    return {"count": str(review_count)} if window is CardWindow.REVIEW else {}


def is_card_markup(markup: object) -> bool:
    """True for the card's resting keyboard: plain `ReceiptCallback` buttons, which are not
    tied to a dialog context (see `PlainKeyboardFactory`)."""
    if not isinstance(markup, InlineKeyboardMarkup):
        return False
    prefix = f"{ReceiptCallback.__prefix__}{ReceiptCallback.__separator__}"
    return any(
        (button.callback_data or "").startswith(prefix)
        for row in markup.inline_keyboard
        for button in row
    )
