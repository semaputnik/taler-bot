from aiogram.enums import ParseMode
from aiogram_dialog import Dialog, DialogManager, Window
from aiogram_dialog.widgets.kbd import Button, Row, ScrollingGroup, Select
from aiogram_dialog.widgets.text import Format

from src.bot.handlers.dialog.common import TransferKeys
from src.bot.handlers.dialog.receipt_card import click_event
from src.bot.handlers.dialog.receipt_card.common import DialogDataKeys, PreviewDataKeys
from src.bot.handlers.dialog.receipt_card.getters import item_getter, items_getter, main_getter
from src.bot.handlers.dialog.widgets import I18nText
from src.bot.states.receipt_card import ReceiptCardSG

ITEMS_PER_PAGE = 8


async def on_start(start_data: dict, manager: DialogManager) -> None:
    manager.dialog_data[DialogDataKeys.RECEIPT_ID] = start_data[TransferKeys.RECEIPT_ID]


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
            Row(
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
