from aiogram.enums import ParseMode
from aiogram_dialog import Dialog, DialogManager, Window
from aiogram_dialog.widgets.kbd import Button, Row, ScrollingGroup, Select
from aiogram_dialog.widgets.media import DynamicMedia
from aiogram_dialog.widgets.text import Const, Format
from magic_filter import F

from src.bot.handlers.dialog.common import TransferKeys
from src.bot.handlers.dialog.receipt_card import click_event
from src.bot.handlers.dialog.receipt_card.common import DialogDataKeys, PreviewDataKeys
from src.bot.handlers.dialog.receipt_card.getters import (
    issue_getter,
    item_getter,
    items_getter,
    main_getter,
    photo_getter,
    review_done_getter,
)
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
            Button(
                I18nText("button-items"),
                id="items",
                on_click=click_event.show_items,
                when=PreviewDataKeys.HAS_ITEMS,
            ),
            Button(
                I18nText("button-review", count=PreviewDataKeys.REVIEW_COUNT),
                id="review",
                on_click=click_event.show_review,
                when=PreviewDataKeys.REVIEW_COUNT,
            ),
            Row(
                Button(I18nText("button-photo"), id="photo", on_click=click_event.show_photo),
                Button(
                    I18nText("button-delete"),
                    id="delete",
                    on_click=click_event.ask_delete,
                    when=PreviewDataKeys.CAN_DELETE,
                ),
                Button(I18nText("button-close"), id="close", on_click=click_event.close),
            ),
            getter=main_getter,
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
            Button(I18nText("button-close"), id="close", on_click=click_event.close),
            Button(
                I18nText("button-back"),
                id="back",
                on_click=click_event.back_to_main,
                when=~F[PreviewDataKeys.HAS_ISSUE],
            ),
            getter=issue_getter,
            state=ReceiptCardSG.issue,
            parse_mode=ParseMode.HTML,
        ),
        Window(
            # Placeholder: the value entry arrives with the next ticket.
            I18nText("issue-input-prompt"),
            Button(I18nText("button-back"), id="back", on_click=click_event.back_to_issue),
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
