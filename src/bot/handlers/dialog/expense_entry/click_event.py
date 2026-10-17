from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.types import CallbackQuery, Message
from aiogram_dialog import DialogManager
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import Button, Select
from fluentogram import TranslatorRunner

from src.bot import render
from src.bot.handlers.dialog import pickers
from src.bot.handlers.dialog.expense_entry.common import DialogDataKeys
from src.bot.handlers.dialog.receipt_card.values import InvalidValue, parse_value
from src.bot.states.expense_entry import ExpenseEntrySG
from src.exception import (
    InvalidEdit,
    InvalidExpense,
    InvalidPaymentSource,
    UnknownPayee,
    UnknownPaymentSource,
)
from src.services.container import Services
from src.services.results import CurrentUser, ExpenseDraft

# --- moving between steps ---------------------------------------------------------------------


async def _enter(manager: DialogManager, state) -> None:
    manager.dialog_data.pop(DialogDataKeys.INPUT_ERROR, None)
    await manager.switch_to(state)


def go_back(state):
    """The click handler of a `◀ Back` button: one step back, nothing kept from the error."""

    async def handler(query: CallbackQuery, button: Button, manager: DialogManager) -> None:
        await _enter(manager, state)

    return handler


def _refuse(manager: DialogManager) -> None:
    """Keep the window; the next render shows its error line."""
    manager.dialog_data[DialogDataKeys.INPUT_ERROR] = True


def _text_of(message: Message) -> str:
    if message.text is None:
        raise InvalidValue("not a text")
    return message.text


# --- payee ------------------------------------------------------------------------------------


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
    data = manager.dialog_data
    data[DialogDataKeys.PAYEE_KEY] = payee.payee_key
    data.pop(DialogDataKeys.PAYEE_NAME, None)
    await _enter(manager, ExpenseEntrySG.source)


async def type_payee_name(query: CallbackQuery, button: Button, manager: DialogManager) -> None:
    await _enter(manager, ExpenseEntrySG.payee_name)


async def on_payee_name(message: Message, widget: MessageInput, manager: DialogManager) -> None:
    user: CurrentUser = manager.middleware_data["user"]
    try:
        name = str(parse_value("text", _text_of(message), ZoneInfo(user.timezone)))
    except InvalidValue:
        _refuse(manager)
        return
    data = manager.dialog_data
    data[DialogDataKeys.PAYEE_NAME] = name
    data.pop(DialogDataKeys.PAYEE_KEY, None)
    await _enter(manager, ExpenseEntrySG.source)


# --- source -----------------------------------------------------------------------------------


async def pick_source(
    query: CallbackQuery, widget: Select, manager: DialogManager, item_id: str
) -> None:
    services: Services = manager.middleware_data["services"]
    user: CurrentUser = manager.middleware_data["user"]
    i18n: TranslatorRunner = manager.middleware_data["i18n"]
    if (
        item_id != pickers.CASH_ID
        and await pickers.resolve_source(services, user.id, item_id) is None
    ):
        await query.answer(i18n.get("entry-pick-gone"), show_alert=True)
        return
    data = manager.dialog_data
    data[DialogDataKeys.SOURCE] = item_id
    data.pop(DialogDataKeys.NEW_CARD, None)
    await _enter(manager, ExpenseEntrySG.category)


async def type_new_card(query: CallbackQuery, button: Button, manager: DialogManager) -> None:
    await _enter(manager, ExpenseEntrySG.new_card)


async def on_new_card(message: Message, widget: MessageInput, manager: DialogManager) -> None:
    """A name for the card to create. A name another source already has (ignoring case) is
    refused here; the domain checks it again when the entry is saved."""
    services: Services = manager.middleware_data["services"]
    user: CurrentUser = manager.middleware_data["user"]
    i18n: TranslatorRunner = manager.middleware_data["i18n"]
    try:
        name = str(parse_value("text", _text_of(message), ZoneInfo(user.timezone)))
    except InvalidValue:
        _refuse(manager)
        return
    taken = {s.name.casefold() for s in await services.expenses.payment_sources(user.id)}
    if name.casefold() in taken | {i18n.get("button-cash").casefold()}:
        _refuse(manager)
        return
    data = manager.dialog_data
    data[DialogDataKeys.NEW_CARD] = name
    data.pop(DialogDataKeys.SOURCE, None)
    await _enter(manager, ExpenseEntrySG.category)


# --- category and date ------------------------------------------------------------------------


async def pick_category(
    query: CallbackQuery, widget: Select, manager: DialogManager, item_id: str
) -> None:
    manager.dialog_data[DialogDataKeys.CATEGORY] = item_id
    await _enter(manager, ExpenseEntrySG.date)


def _today(user: CurrentUser) -> date:
    return datetime.now(ZoneInfo(user.timezone)).date()


async def _pick_date(manager: DialogManager, day: date) -> None:
    manager.dialog_data[DialogDataKeys.SPENT_AT] = day.isoformat()
    await _enter(manager, ExpenseEntrySG.tags)


async def pick_today(query: CallbackQuery, button: Button, manager: DialogManager) -> None:
    await _pick_date(manager, _today(manager.middleware_data["user"]))


async def pick_yesterday(query: CallbackQuery, button: Button, manager: DialogManager) -> None:
    await _pick_date(manager, _today(manager.middleware_data["user"]) - timedelta(days=1))


async def type_date(query: CallbackQuery, button: Button, manager: DialogManager) -> None:
    await _enter(manager, ExpenseEntrySG.date_text)


async def on_date(message: Message, widget: MessageInput, manager: DialogManager) -> None:
    user: CurrentUser = manager.middleware_data["user"]
    try:
        day = parse_value("date", _text_of(message), ZoneInfo(user.timezone))
    except InvalidValue:
        _refuse(manager)
        return
    assert isinstance(day, date)
    await _pick_date(manager, day)


# --- tags and the end of the entry --------------------------------------------------------------


async def on_tags(message: Message, widget: MessageInput, manager: DialogManager) -> None:
    try:
        text = _text_of(message)
    except InvalidValue:
        _refuse(manager)
        return
    await _save(manager, message.chat.id, text.split(","))


async def skip_tags(query: CallbackQuery, button: Button, manager: DialogManager) -> None:
    if query.message is None:
        return
    await _save(manager, query.message.chat.id, [])


async def _save(manager: DialogManager, chat_id: int, tags: list[str]) -> None:
    """The last step: record the expense in one service call and send it as a message. Nothing
    was written before this. A value the domain refuses sends the user back to the step that
    holds it, with its error line; the answers given so far are kept."""
    services: Services = manager.middleware_data["services"]
    user: CurrentUser = manager.middleware_data["user"]
    i18n: TranslatorRunner = manager.middleware_data["i18n"]
    bot: Bot = manager.middleware_data["bot"]
    data = manager.dialog_data
    source = data.get(DialogDataKeys.SOURCE)
    draft = ExpenseDraft(
        amount=Decimal(data[DialogDataKeys.AMOUNT]),
        spent_at=date.fromisoformat(data[DialogDataKeys.SPENT_AT]),
        category=data[DialogDataKeys.CATEGORY],
        payee_key=data.get(DialogDataKeys.PAYEE_KEY),
        payee_name=data.get(DialogDataKeys.PAYEE_NAME),
        payment_source_id=int(source) if source not in (None, pickers.CASH_ID) else None,
        cash=source == pickers.CASH_ID,
        new_card_name=data.get(DialogDataKeys.NEW_CARD),
        tags=tags,
    )
    try:
        card = await services.expenses.add_manual(user.id, draft)
    except InvalidExpense:  # the tags: too many, or one too long
        _refuse(manager)
        return
    except InvalidEdit:  # a payee name without letters or digits
        await _back_with_error(manager, ExpenseEntrySG.payee_name)
        return
    except InvalidPaymentSource:  # a card name that is taken or reserved
        await _back_with_error(manager, ExpenseEntrySG.new_card)
        return
    except (UnknownPayee, UnknownPaymentSource) as error:  # gone since it was picked
        await bot.send_message(chat_id, i18n.get("entry-pick-gone"))
        await _enter(
            manager,
            ExpenseEntrySG.payee if isinstance(error, UnknownPayee) else ExpenseEntrySG.source,
        )
        return
    await bot.send_message(chat_id, render.expense_text(card, i18n), parse_mode=ParseMode.HTML)
    await manager.done()


async def _back_with_error(manager: DialogManager, state) -> None:
    await manager.switch_to(state)
    _refuse(manager)
