"""The tags window both cards share: the prompt with the current tags, the typed comma-separated
line, the `🧹 Clear` button. Each card supplies what differs: where the tags are loaded from, how
a change is saved, and where `◀ Back` goes."""

from aiogram.enums import ContentType, ParseMode
from aiogram.types import Message
from aiogram_dialog import Window
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import Button
from aiogram_dialog.widgets.text import Format
from fluentogram import TranslatorRunner

from src.bot import render
from src.bot.handlers.dialog.receipt_card.values import InvalidValue
from src.bot.handlers.dialog.widgets import I18nText

TEXT = "text"  # the window data key of the prompt (the same as both cards' PreviewDataKeys.TEXT)
PROMPT_KEY = "expense-edit-tags"


def prompt_data(tags: list[str], i18n: TranslatorRunner, *, refused: bool) -> dict:
    """The window data: the current tags as hashtags (`not specified` when none), and the error
    line under the prompt after a refused line."""
    shown = " ".join(tag for tag in map(render.hashtag, tags) if tag)
    text = i18n.get(PROMPT_KEY, tags=shown or i18n.get("item-not-specified"))
    if refused:
        text = f"{text}\n\n{i18n.get(f'{PROMPT_KEY}-error')}"
    return {TEXT: text}


def tags_of(message: Message) -> list[str]:
    """The tags a typed line holds (comma-separated; the domain normalizes and validates them).
    Raises InvalidValue for anything that is not text."""
    if message.text is None:
        raise InvalidValue("not a text")
    return message.text.split(",")


def tags_window(state, getter, on_input, on_clear, back: Button) -> Window:
    """The window: the prompt, a text input, `🧹 Clear`, and the card's own Back button."""
    return Window(
        Format(f"{{{TEXT}}}"),
        MessageInput(on_input, content_types=ContentType.ANY),
        Button(I18nText("button-clear"), id="clear", on_click=on_clear),
        back,
        getter=getter,
        state=state,
        parse_mode=ParseMode.HTML,
    )
