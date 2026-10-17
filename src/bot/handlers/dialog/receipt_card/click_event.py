from zoneinfo import ZoneInfo

from aiogram.types import CallbackQuery, Message
from aiogram_dialog import DialogManager
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import Button, Select
from fluentogram import TranslatorRunner

from src.bot.handlers.dialog.receipt_card.common import DialogDataKeys
from src.bot.handlers.dialog.receipt_card.values import InvalidValue, parse_value
from src.bot.states.receipt_card import ReceiptCardSG
from src.exception import (
    InvalidEdit,
    InvalidIssueResolution,
    InvalidReceiptTransition,
    ReceiptNotFound,
    UnknownIssue,
)
from src.services.container import Services
from src.services.results import CurrentUser, IssueCard


async def ask_delete(query: CallbackQuery, button: Button, manager: DialogManager) -> None:
    await manager.switch_to(ReceiptCardSG.delete_confirm)


async def show_items(query: CallbackQuery, button: Button, manager: DialogManager) -> None:
    await manager.switch_to(ReceiptCardSG.items)


async def back_to_items(query: CallbackQuery, button: Button, manager: DialogManager) -> None:
    await manager.switch_to(ReceiptCardSG.items)


async def select_item(
    query: CallbackQuery, widget: Select, manager: DialogManager, item_id: str
) -> None:
    """Remember the tapped item's ref. A row carries only its position (a ref can be too long
    for callback data), so the ref comes from the current list."""
    services: Services = manager.middleware_data["services"]
    user: CurrentUser = manager.middleware_data["user"]
    i18n: TranslatorRunner = manager.middleware_data["i18n"]
    rows = await services.receipts.items(user.id, manager.dialog_data[DialogDataKeys.RECEIPT_ID])
    position = int(item_id)
    if position >= len(rows):
        await query.answer(i18n.get("item-gone"), show_alert=True)
        return
    manager.dialog_data[DialogDataKeys.ITEM_REF] = rows[position].ref
    await manager.switch_to(ReceiptCardSG.item)


async def show_review(query: CallbackQuery, button: Button, manager: DialogManager) -> None:
    await start_review(manager)


async def start_review(manager: DialogManager) -> None:
    """Load the walk once and show its first open issue; with nothing to review, show `main`."""
    services: Services = manager.middleware_data["services"]
    user: CurrentUser = manager.middleware_data["user"]
    cards = await services.receipts.review(user.id, manager.dialog_data[DialogDataKeys.RECEIPT_ID])
    data = manager.dialog_data
    data[DialogDataKeys.WALK] = [card.issue_id for card in cards]
    data[DialogDataKeys.POSITION] = 0
    data[DialogDataKeys.CONFIRMED] = data[DialogDataKeys.CORRECTED] = 0
    data[DialogDataKeys.SKIPPED] = 0
    await _show_current(manager, cards)


def settle(manager: DialogManager, cards: list[IssueCard]) -> IssueCard | None:
    """Move the position forward to the first walk issue that is still reviewable (an issue
    resolved from another device is skipped silently). None when the walk is over."""
    data = manager.dialog_data
    by_id = {card.issue_id: card for card in cards}
    walk: list[int] = data[DialogDataKeys.WALK]
    position: int = data[DialogDataKeys.POSITION]
    while position < len(walk) and walk[position] not in by_id:
        position += 1
    data[DialogDataKeys.POSITION] = position
    if position >= len(walk):
        data.pop(DialogDataKeys.CURRENT_ISSUE_ID, None)
        return None
    data[DialogDataKeys.CURRENT_ISSUE_ID] = walk[position]
    return by_id[walk[position]]


async def advance(manager: DialogManager) -> None:
    """Step past the issue on screen: show the next open one, or the tally after the last.
    Every action that closes an issue (Skip, Correct, a later entered value) ends here."""
    services: Services = manager.middleware_data["services"]
    user: CurrentUser = manager.middleware_data["user"]
    manager.dialog_data[DialogDataKeys.POSITION] += 1
    cards = await services.receipts.review(user.id, manager.dialog_data[DialogDataKeys.RECEIPT_ID])
    await _show_current(manager, cards)


async def _show_current(manager: DialogManager, cards: list[IssueCard]) -> None:
    if settle(manager, cards) is not None:
        await manager.switch_to(ReceiptCardSG.issue)
    elif manager.dialog_data[DialogDataKeys.WALK]:
        await manager.switch_to(ReceiptCardSG.review_done)
    else:
        await manager.switch_to(ReceiptCardSG.main)


async def confirm_issue(query: CallbackQuery, button: Button, manager: DialogManager) -> None:
    await _resolve(query, manager, "confirmed", DialogDataKeys.CONFIRMED)


async def skip_issue(query: CallbackQuery, button: Button, manager: DialogManager) -> None:
    await _resolve(query, manager, "skipped", DialogDataKeys.SKIPPED)


async def _resolve(
    query: CallbackQuery, manager: DialogManager, resolution: str, counter: str
) -> None:
    services: Services = manager.middleware_data["services"]
    user: CurrentUser = manager.middleware_data["user"]
    i18n: TranslatorRunner = manager.middleware_data["i18n"]
    data = manager.dialog_data
    try:
        await services.receipts.resolve_issue(
            user.id,
            data[DialogDataKeys.RECEIPT_ID],
            data[DialogDataKeys.CURRENT_ISSUE_ID],
            resolution,
        )
    except ReceiptNotFound, InvalidReceiptTransition:
        # The receipt was deleted while the walk was open.
        await query.answer(i18n.get("card-deleted-alert"), show_alert=True)
        await manager.switch_to(ReceiptCardSG.main)
        return
    except UnknownIssue, InvalidIssueResolution:
        pass  # resolved from another device meanwhile: nothing to record, just move on
    else:
        data[counter] += 1
    await advance(manager)


async def enter_value(query: CallbackQuery, button: Button, manager: DialogManager) -> None:
    manager.dialog_data.pop(DialogDataKeys.INPUT_ERROR, None)
    await manager.switch_to(ReceiptCardSG.issue_input)


async def back_to_issue(query: CallbackQuery, button: Button, manager: DialogManager) -> None:
    manager.dialog_data.pop(DialogDataKeys.INPUT_ERROR, None)
    await manager.switch_to(ReceiptCardSG.issue)


async def on_value(message: Message, widget: MessageInput, manager: DialogManager) -> None:
    """The user typed (or sent) something in the entry window. A text that parses is given to
    `correct_issue`; anything else keeps the window and the open issue, with the error line."""
    services: Services = manager.middleware_data["services"]
    user: CurrentUser = manager.middleware_data["user"]
    i18n: TranslatorRunner = manager.middleware_data["i18n"]
    data = manager.dialog_data
    cards = await services.receipts.review(user.id, data[DialogDataKeys.RECEIPT_ID])
    current = next((c for c in cards if c.issue_id == data[DialogDataKeys.CURRENT_ISSUE_ID]), None)
    if current is None or not current.editable:
        await advance(manager)  # resolved elsewhere meanwhile
        return
    try:
        if message.text is None:
            raise InvalidValue("not a text")
        value = parse_value(current.input_kind, message.text, ZoneInfo(user.timezone))
        await services.receipts.correct_issue(
            user.id, data[DialogDataKeys.RECEIPT_ID], current.issue_id, value
        )
    except InvalidValue, InvalidEdit:
        data[DialogDataKeys.INPUT_ERROR] = True
        return
    except ReceiptNotFound, InvalidReceiptTransition:
        await message.answer(i18n.get("card-deleted-alert"))
        await manager.switch_to(ReceiptCardSG.main)
        return
    except UnknownIssue, InvalidIssueResolution:
        pass  # resolved from another device meanwhile: nothing to record, just move on
    else:
        data[DialogDataKeys.CORRECTED] += 1
    data.pop(DialogDataKeys.INPUT_ERROR, None)
    await advance(manager)


async def show_photo(query: CallbackQuery, button: Button, manager: DialogManager) -> None:
    await manager.switch_to(ReceiptCardSG.photo)


async def back_to_main(query: CallbackQuery, button: Button, manager: DialogManager) -> None:
    await manager.switch_to(ReceiptCardSG.main)


async def confirm_delete(query: CallbackQuery, button: Button, manager: DialogManager) -> None:
    services: Services = manager.middleware_data["services"]
    user: CurrentUser = manager.middleware_data["user"]
    i18n: TranslatorRunner = manager.middleware_data["i18n"]
    receipt_id = manager.dialog_data[DialogDataKeys.RECEIPT_ID]
    try:
        await services.receipts.soft_delete(user.id, receipt_id)
    except InvalidReceiptTransition:
        # Either the receipt is still being read, or it was deleted meanwhile.
        if await _is_deleted(services, user.id, receipt_id):
            await query.answer(i18n.get("card-deleted-alert"), show_alert=True)
            await manager.switch_to(ReceiptCardSG.main)
        else:
            await query.answer(i18n.get("card-cannot-delete-parsing"), show_alert=True)
            await manager.switch_to(ReceiptCardSG.main)
        return
    except ReceiptNotFound:
        await query.answer(i18n.get("card-deleted-alert"), show_alert=True)
        await manager.switch_to(ReceiptCardSG.main)
        return
    await query.answer()
    await manager.switch_to(ReceiptCardSG.main)  # shows the deleted text, with no buttons


async def _is_deleted(services: Services, user_id: int, receipt_id: int) -> bool:
    try:
        return (await services.receipts.card(user_id, receipt_id)).deleted
    except ReceiptNotFound:
        return True
