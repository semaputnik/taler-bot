from aiogram.enums import ContentType, ParseMode
from aiogram_dialog import Dialog, DialogManager, Window
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import Button, Row
from aiogram_dialog.widgets.text import Format

from src.bot.handlers.dialog import pickers
from src.bot.handlers.dialog.cards import PlainKeyboardFactory
from src.bot.handlers.dialog.common import TransferKeys
from src.bot.handlers.dialog.expense_card import click_event, getters
from src.bot.handlers.dialog.expense_card.common import DialogDataKeys, PreviewDataKeys
from src.bot.handlers.dialog.expense_card.keyboard import expense_card_keyboard
from src.bot.handlers.dialog.widgets import I18nText
from src.bot.states.expense_card import ExpenseCardSG


async def on_start(start_data: dict, manager: DialogManager) -> None:
    manager.dialog_data[DialogDataKeys.EXPENSE_ID] = start_data[TransferKeys.EXPENSE_ID]


def _window(state, getter, *widgets) -> Window:
    return Window(
        Format(f"{{{PreviewDataKeys.TEXT}}}"),
        *widgets,
        getter=getter,
        state=state,
        parse_mode=ParseMode.HTML,
    )


def _back(to=ExpenseCardSG.main) -> Button:
    return Button(I18nText("button-back"), id="back", on_click=click_event.go(to))


def _text_input(handler) -> MessageInput:
    return MessageInput(handler, content_types=ContentType.ANY)


def create_expense_card_dialog() -> Dialog:
    """A new dialog per dispatcher: a router can be attached to one parent only."""
    S = ExpenseCardSG
    return Dialog(
        Window(
            Format(f"{{{PreviewDataKeys.TEXT}}}"),
            expense_card_keyboard(),
            getter=getters.main_getter,
            markup_factory=PlainKeyboardFactory(),
            state=S.main,
            parse_mode=ParseMode.HTML,
        ),
        _window(S.amount, getters.amount_getter, _text_input(click_event.on_amount), _back()),
        _window(
            S.payee,
            getters.payee_getter,
            pickers.payee_select(click_event.pick_payee, id_="card_payee"),
            Button(
                I18nText("button-type-name"),
                id="type_name",
                on_click=click_event.go(S.payee_name),
            ),
            _back(),
        ),
        _window(
            S.payee_name,
            getters.payee_name_getter,
            _text_input(click_event.on_payee_name),
            _back(S.payee),
        ),
        _window(
            S.source,
            getters.source_getter,
            pickers.source_select(click_event.pick_source, id_="card_source"),
            Button(I18nText("button-new-card"), id="new_card", on_click=click_event.go(S.new_card)),
            Button(
                I18nText("button-rename"),
                id="rename",
                on_click=click_event.go(S.source_rename),
                when=PreviewDataKeys.CAN_RENAME,
            ),
            _back(),
        ),
        _window(
            S.new_card,
            getters.new_card_getter,
            _text_input(click_event.on_new_card),
            _back(S.source),
        ),
        _window(
            S.source_rename,
            getters.rename_getter,
            _text_input(click_event.on_rename),
            _back(S.source),
        ),
        _window(
            S.category,
            getters.category_getter,
            pickers.category_select(click_event.pick_category, id_="card_category"),
            _back(),
        ),
        _window(
            S.date,
            getters.date_getter,
            Row(
                Button(I18nText("button-today"), id="today", on_click=click_event.pick_today),
                Button(
                    I18nText("button-yesterday"),
                    id="yesterday",
                    on_click=click_event.pick_yesterday,
                ),
            ),
            Button(I18nText("button-other-date"), id="other", on_click=click_event.go(S.date_text)),
            _back(),
        ),
        _window(
            S.date_text, getters.date_text_getter, _text_input(click_event.on_date), _back(S.date)
        ),
        _window(
            S.tags,
            getters.tags_getter,
            _text_input(click_event.on_tags),
            Button(I18nText("button-clear"), id="clear", on_click=click_event.clear_tags),
            _back(),
        ),
        Window(
            I18nText("expense-delete-confirm"),
            Row(
                Button(
                    I18nText("button-delete-confirm"),
                    id="confirm_delete",
                    on_click=click_event.confirm_delete,
                ),
                _back(),
            ),
            state=S.delete_confirm,
            parse_mode=ParseMode.HTML,
        ),
        on_start=on_start,
    )
