from aiogram.enums import ContentType, ParseMode
from aiogram_dialog import Dialog, DialogManager, Window
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import Button, Row
from aiogram_dialog.widgets.text import Format

from src.bot.handlers.dialog import pickers
from src.bot.handlers.dialog.common import TransferKeys
from src.bot.handlers.dialog.expense_entry import click_event, getters
from src.bot.handlers.dialog.expense_entry.common import DialogDataKeys, PreviewDataKeys
from src.bot.handlers.dialog.widgets import I18nText
from src.bot.states.expense_entry import ExpenseEntrySG


async def on_start(start_data: dict, manager: DialogManager) -> None:
    manager.dialog_data[DialogDataKeys.AMOUNT] = start_data[TransferKeys.AMOUNT]


def _window(state, getter, *widgets) -> Window:
    return Window(
        Format(f"{{{PreviewDataKeys.TEXT}}}"),
        *widgets,
        getter=getter,
        state=state,
        parse_mode=ParseMode.HTML,
    )


def _back(to) -> Button:
    return Button(I18nText("button-back"), id="back", on_click=click_event.go_back(to))


def _text_input(handler) -> MessageInput:
    return MessageInput(handler, content_types=ContentType.ANY)


def create_expense_entry_dialog() -> Dialog:
    """A new dialog per dispatcher: a router can be attached to one parent only."""
    return Dialog(
        _window(
            ExpenseEntrySG.payee,
            getters.payee_getter,
            pickers.payee_select(click_event.pick_payee),
            Button(
                I18nText("button-type-name"), id="type_name", on_click=click_event.type_payee_name
            ),
        ),
        _window(
            ExpenseEntrySG.payee_name,
            getters.payee_name_getter,
            _text_input(click_event.on_payee_name),
            _back(ExpenseEntrySG.payee),
        ),
        _window(
            ExpenseEntrySG.source,
            getters.source_getter,
            pickers.source_select(click_event.pick_source),
            Button(I18nText("button-new-card"), id="new_card", on_click=click_event.type_new_card),
            _back(ExpenseEntrySG.payee),
        ),
        _window(
            ExpenseEntrySG.new_card,
            getters.new_card_getter,
            _text_input(click_event.on_new_card),
            _back(ExpenseEntrySG.source),
        ),
        _window(
            ExpenseEntrySG.category,
            getters.category_getter,
            pickers.category_select(click_event.pick_category),
            _back(ExpenseEntrySG.source),
        ),
        _window(
            ExpenseEntrySG.date,
            getters.date_getter,
            Row(
                Button(I18nText("button-today"), id="today", on_click=click_event.pick_today),
                Button(
                    I18nText("button-yesterday"),
                    id="yesterday",
                    on_click=click_event.pick_yesterday,
                ),
            ),
            Button(I18nText("button-other-date"), id="other", on_click=click_event.type_date),
            _back(ExpenseEntrySG.category),
        ),
        _window(
            ExpenseEntrySG.date_text,
            getters.date_text_getter,
            _text_input(click_event.on_date),
            _back(ExpenseEntrySG.date),
        ),
        _window(
            ExpenseEntrySG.tags,
            getters.tags_getter,
            _text_input(click_event.on_tags),
            Button(I18nText("button-skip"), id="skip", on_click=click_event.skip_tags),
            _back(ExpenseEntrySG.date),
        ),
        on_start=on_start,
    )
