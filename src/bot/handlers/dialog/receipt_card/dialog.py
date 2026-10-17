from aiogram.enums import ContentType, ParseMode
from aiogram_dialog import Dialog, DialogManager, Window
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import Button, Row, ScrollingGroup, Select
from aiogram_dialog.widgets.media import DynamicMedia
from aiogram_dialog.widgets.text import Const, Format

from src.bot.handlers.dialog.common import TransferKeys
from src.bot.handlers.dialog.receipt_card import click_event
from src.bot.handlers.dialog.receipt_card.common import DialogDataKeys, PreviewDataKeys
from src.bot.handlers.dialog.receipt_card.getters import (
    issue_getter,
    issue_input_getter,
    item_getter,
    items_getter,
    main_getter,
    photo_getter,
    review_done_getter,
)
from src.bot.handlers.dialog.receipt_card.keyboard import CardKeyboard, PlainKeyboardFactory
from src.bot.handlers.dialog.widgets import I18nText
from src.bot.states.receipt_card import ReceiptCardSG

ITEMS_PER_PAGE = 8


async def on_start(start_data: dict, manager: DialogManager) -> None:
    manager.dialog_data[DialogDataKeys.RECEIPT_ID] = start_data[TransferKeys.RECEIPT_ID]
    if manager.current_context().state == ReceiptCardSG.issue:
        await click_event.start_review(manager)  # the summary's Review button


def create_receipt_card_dialog() -> Dialog:
    """A new dialog per dispatcher: a router can be attached to one parent only."""
    return Dialog(
        Window(
            Format(f"{{{PreviewDataKeys.TEXT}}}"),
            CardKeyboard(),
            getter=main_getter,
            markup_factory=PlainKeyboardFactory(),
            state=ReceiptCardSG.main,
            parse_mode=ParseMode.HTML,
        ),
        Window(
            Format(f"{{{PreviewDataKeys.TEXT}}}"),
            ScrollingGroup(
                Select(
                    Format("{item.text}"),
                    id="item",
                    item_id_getter=lambda choice: choice.id,
                    items=PreviewDataKeys.ITEMS,
                    on_click=click_event.select_item,
                ),
                id="items_pager",
                width=1,
                height=ITEMS_PER_PAGE,
                hide_on_single_page=True,
            ),
            Button(I18nText("button-back"), id="back", on_click=click_event.back_to_main),
            getter=items_getter,
            state=ReceiptCardSG.items,
            parse_mode=ParseMode.HTML,
        ),
        Window(
            Format(f"{{{PreviewDataKeys.TEXT}}}"),
            Button(I18nText("button-back"), id="back", on_click=click_event.back_to_items),
            getter=item_getter,
            state=ReceiptCardSG.item,
            parse_mode=ParseMode.HTML,
        ),
        Window(
            Format(f"{{{PreviewDataKeys.TEXT}}}"),
            Button(
                I18nText("button-correct"),
                id="correct",
                on_click=click_event.confirm_issue,
                when=PreviewDataKeys.HAS_ISSUE,
            ),
            Button(
                I18nText("button-enter-value"),
                id="enter_value",
                on_click=click_event.enter_value,
                when=PreviewDataKeys.CAN_ENTER_VALUE,
            ),
            Button(
                I18nText("button-skip"),
                id="skip",
                on_click=click_event.skip_issue,
                when=PreviewDataKeys.HAS_ISSUE,
            ),
            Button(I18nText("button-back"), id="back", on_click=click_event.back_to_main),
            getter=issue_getter,
            state=ReceiptCardSG.issue,
            parse_mode=ParseMode.HTML,
        ),
        Window(
            Format(f"{{{PreviewDataKeys.TEXT}}}"),
            MessageInput(click_event.on_value, content_types=ContentType.ANY),
            Button(I18nText("button-back"), id="back", on_click=click_event.back_to_issue),
            getter=issue_input_getter,
            state=ReceiptCardSG.issue_input,
            parse_mode=ParseMode.HTML,
        ),
        Window(
            Format(f"{{{PreviewDataKeys.TEXT}}}"),
            Button(I18nText("button-back"), id="back", on_click=click_event.back_to_main),
            getter=review_done_getter,
            state=ReceiptCardSG.review_done,
            parse_mode=ParseMode.HTML,
        ),
        Window(
            Const(""),
            DynamicMedia(PreviewDataKeys.PHOTO),
            Button(I18nText("button-back"), id="back", on_click=click_event.back_to_main),
            getter=photo_getter,
            state=ReceiptCardSG.photo,
        ),
        Window(
            I18nText("card-delete-confirm"),
            Row(
                Button(
                    I18nText("button-delete-confirm"),
                    id="confirm_delete",
                    on_click=click_event.confirm_delete,
                ),
                Button(I18nText("button-back"), id="back", on_click=click_event.back_to_main),
            ),
            state=ReceiptCardSG.delete_confirm,
            parse_mode=ParseMode.HTML,
        ),
        on_start=on_start,
    )
