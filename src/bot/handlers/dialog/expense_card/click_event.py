from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram.fsm.state import State
from aiogram.types import CallbackQuery, Message
from aiogram_dialog import DialogManager, ShowMode
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import Button, Select
from fluentogram import TranslatorRunner

from src.bot.handlers.dialog import pickers
from src.bot.handlers.dialog.expense_card.common import DialogDataKeys
from src.bot.handlers.dialog.receipt_card.values import InvalidValue, parse_value
from src.bot.handlers.dialog.tags import tags_of
from src.bot.states.expense_card import ExpenseCardSG
from src.exception import (
    ExpenseNotFound,
    InvalidEdit,
    InvalidExpense,
    InvalidPaymentSource,
    UnknownPayee,
    UnknownPaymentSource,
)
from src.services.container import Services
from src.services.results import CurrentUser

Change = Callable[[Services, CurrentUser, int], Awaitable[object]]

# A typed value arrives as a message, where aiogram-dialog would send a new message by default.
# The card is one message that changes where it is, so every outcome edits it in place.

# --- moving between windows ---------------------------------------------------------------------


async def _enter(manager: DialogManager, state: State) -> None:
    manager.dialog_data.pop(DialogDataKeys.INPUT_ERROR, None)
    await manager.switch_to(state, show_mode=ShowMode.EDIT)


def go(state: State):
    """The click handler of a button that opens another window of the card."""

    async def handler(query: CallbackQuery, button: Button, manager: DialogManager) -> None:
        await _enter(manager, state)

    return handler


def _refuse(manager: DialogManager) -> None:
    """Keep the window; the next render shows its error line."""
    manager.dialog_data[DialogDataKeys.INPUT_ERROR] = True
    manager.show_mode = ShowMode.EDIT


def _text_of(message: Message) -> str:
    if message.text is None:
        raise InvalidValue("not a text")
    return message.text


# --- one change ---------------------------------------------------------------------------------


async def _is_open(manager: DialogManager) -> bool:
    services: Services = manager.middleware_data["services"]
    user: CurrentUser = manager.middleware_data["user"]
    try:
        card = await services.expenses.card(user.id, manager.dialog_data[DialogDataKeys.EXPENSE_ID])
    except ExpenseNotFound:
        return False
    return not card.deleted


async def _apply(manager: DialogManager, query: CallbackQuery | None, change: Change) -> bool:
    """Run one service change on the card's expense and go back to `main`.

    An expense that was deleted meanwhile alerts (for a tap) and shows the deleted text. A value
    the domain refuses keeps the window with its error line. Returns whether the change was
    saved.
    """
    services: Services = manager.middleware_data["services"]
    user: CurrentUser = manager.middleware_data["user"]
    i18n: TranslatorRunner = manager.middleware_data["i18n"]
    expense_id = manager.dialog_data[DialogDataKeys.EXPENSE_ID]
    try:
        await change(services, user, expense_id)
    except ExpenseNotFound, InvalidExpense, InvalidEdit, InvalidPaymentSource:
        if not await _is_open(manager):
            await _gone(manager, query, i18n)
            return False
        _refuse(manager)
        return False
    except UnknownPayee, UnknownPaymentSource:  # gone since it was listed
        if query is not None:
            await query.answer(i18n.get("entry-pick-gone"), show_alert=True)
        return False
    await _enter(manager, ExpenseCardSG.main)
    return True


async def _gone(manager: DialogManager, query: CallbackQuery | None, i18n: TranslatorRunner):
    if query is not None:
        await query.answer(i18n.get("expense-deleted-alert"), show_alert=True)
    await _enter(manager, ExpenseCardSG.main)  # shows the deleted text, with no buttons


# --- amount -------------------------------------------------------------------------------------


async def on_amount(message: Message, widget: MessageInput, manager: DialogManager) -> None:
    user: CurrentUser = manager.middleware_data["user"]
    try:
        amount = parse_value("money", _text_of(message), ZoneInfo(user.timezone))
    except InvalidValue:
        _refuse(manager)
        return
    await _apply(
        manager,
        None,
        lambda services, user, expense_id: services.expenses.set_amount(
            user.id, expense_id, amount
        ),
    )


# --- payee --------------------------------------------------------------------------------------


async def pick_payee(
    query: CallbackQuery, widget: Select, manager: DialogManager, item_id: str
) -> None:
    services: Services = manager.middleware_data["services"]
    user: CurrentUser = manager.middleware_data["user"]
    i18n: TranslatorRunner = manager.middleware_data["i18n"]
    payee = await pickers.resolve_payee(services, user.id, item_id)
    if payee is None:
        await query.answer(i18n.get("entry-pick-gone"), show_alert=True)
        return  # the window renders again with the current list
    await _apply(
        manager,
        query,
        lambda services, user, expense_id: services.expenses.set_payee(
            user.id, expense_id, payee_key=payee.payee_key
        ),
    )


async def on_payee_name(message: Message, widget: MessageInput, manager: DialogManager) -> None:
    user: CurrentUser = manager.middleware_data["user"]
    try:
        name = str(parse_value("text", _text_of(message), ZoneInfo(user.timezone)))
    except InvalidValue:
        _refuse(manager)
        return
    await _apply(
        manager,
        None,
        lambda services, user, expense_id: services.expenses.set_payee(
            user.id, expense_id, payee_name=name
        ),
    )


# --- source -------------------------------------------------------------------------------------


async def pick_source(
    query: CallbackQuery, widget: Select, manager: DialogManager, item_id: str
) -> None:
    services: Services = manager.middleware_data["services"]
    user: CurrentUser = manager.middleware_data["user"]
    i18n: TranslatorRunner = manager.middleware_data["i18n"]
    if item_id == pickers.CASH_ID:

        async def change(services: Services, user: CurrentUser, expense_id: int):
            return await services.expenses.set_source(user.id, expense_id, cash=True)

    else:
        source = await pickers.resolve_source(services, user.id, item_id)
        if source is None:
            await query.answer(i18n.get("entry-pick-gone"), show_alert=True)
            return

        async def change(services: Services, user: CurrentUser, expense_id: int):
            return await services.expenses.set_source(user.id, expense_id, source_id=source.id)

    await _apply(manager, query, change)


async def on_new_card(message: Message, widget: MessageInput, manager: DialogManager) -> None:
    """A name for the card to create and pay with. A taken or reserved name is refused by the
    domain."""
    user: CurrentUser = manager.middleware_data["user"]
    try:
        name = str(parse_value("text", _text_of(message), ZoneInfo(user.timezone)))
    except InvalidValue:
        _refuse(manager)
        return
    await _apply(
        manager,
        None,
        lambda services, user, expense_id: services.expenses.set_source(
            user.id, expense_id, new_card_name=name
        ),
    )


async def on_rename(message: Message, widget: MessageInput, manager: DialogManager) -> None:
    """Rename the card this expense was paid with; every expense paid with it shows the name."""
    services: Services = manager.middleware_data["services"]
    user: CurrentUser = manager.middleware_data["user"]
    i18n: TranslatorRunner = manager.middleware_data["i18n"]
    try:
        name = str(parse_value("text", _text_of(message), ZoneInfo(user.timezone)))
    except InvalidValue:
        _refuse(manager)
        return
    try:
        card = await services.expenses.card(user.id, manager.dialog_data[DialogDataKeys.EXPENSE_ID])
    except ExpenseNotFound:
        await _gone(manager, None, i18n)
        return
    if card.deleted:
        await _gone(manager, None, i18n)
        return
    if card.payment_source_id is None:
        await _enter(manager, ExpenseCardSG.source)
        return
    source_id = card.payment_source_id
    try:
        await services.catalog.rename_source(user.id, source_id, name)
    except InvalidPaymentSource, UnknownPaymentSource:
        _refuse(manager)
        return
    await _enter(manager, ExpenseCardSG.main)


# --- category -----------------------------------------------------------------------------------


async def pick_category(
    query: CallbackQuery, widget: Select, manager: DialogManager, item_id: str
) -> None:
    await _apply(
        manager,
        query,
        lambda services, user, expense_id: services.expenses.set_category(
            user.id, expense_id, item_id
        ),
    )


# --- date ---------------------------------------------------------------------------------------


def _today(user: CurrentUser) -> date:
    return datetime.now(ZoneInfo(user.timezone)).date()


async def _set_date(manager: DialogManager, query: CallbackQuery | None, day: date) -> None:
    await _apply(
        manager,
        query,
        lambda services, user, expense_id: services.expenses.set_date(user.id, expense_id, day),
    )


async def pick_today(query: CallbackQuery, button: Button, manager: DialogManager) -> None:
    await _set_date(manager, query, _today(manager.middleware_data["user"]))


async def pick_yesterday(query: CallbackQuery, button: Button, manager: DialogManager) -> None:
    await _set_date(manager, query, _today(manager.middleware_data["user"]) - timedelta(days=1))


async def on_date(message: Message, widget: MessageInput, manager: DialogManager) -> None:
    user: CurrentUser = manager.middleware_data["user"]
    try:
        day = parse_value("date", _text_of(message), ZoneInfo(user.timezone))
    except InvalidValue:
        _refuse(manager)
        return
    assert isinstance(day, date)
    await _set_date(manager, None, day)


# --- tags ---------------------------------------------------------------------------------------


async def _set_tags(manager: DialogManager, query: CallbackQuery | None, tags: list[str]) -> None:
    await _apply(
        manager,
        query,
        lambda services, user, expense_id: services.expenses.set_tags(user.id, expense_id, tags),
    )


async def on_tags(message: Message, widget: MessageInput, manager: DialogManager) -> None:
    try:
        tags = tags_of(message)
    except InvalidValue:
        _refuse(manager)
        return
    await _set_tags(manager, None, tags)


async def clear_tags(query: CallbackQuery, button: Button, manager: DialogManager) -> None:
    await _set_tags(manager, query, [])


# --- delete -------------------------------------------------------------------------------------


async def confirm_delete(query: CallbackQuery, button: Button, manager: DialogManager) -> None:
    """Delete the expense; the card returns to `main`, which shows the deleted text."""
    await _apply(
        manager,
        query,
        lambda services, user, expense_id: services.expenses.soft_delete(user.id, expense_id),
    )
