from html import escape

from aiogram_dialog import DialogManager
from fluentogram import TranslatorRunner

from src.bot import render
from src.bot.handlers.dialog import pickers, tags
from src.bot.handlers.dialog.expense_card.common import DialogDataKeys, PreviewDataKeys
from src.exception import ExpenseNotFound
from src.services.container import Services
from src.services.results import CurrentUser, ExpenseCard


async def load_card(
    manager: DialogManager, services: Services, user: CurrentUser
) -> ExpenseCard | None:
    """The expense on screen; None when it is missing or deleted (the card then shows the
    deleted text and has no buttons)."""
    try:
        card = await services.expenses.card(user.id, manager.dialog_data[DialogDataKeys.EXPENSE_ID])
    except ExpenseNotFound:
        return None
    return None if card.deleted else card


def _data(text: str, **extra) -> dict:
    return {PreviewDataKeys.TEXT: text} | extra


def _with_error(text: str, key: str, manager: DialogManager, i18n: TranslatorRunner) -> str:
    if manager.dialog_data.get(DialogDataKeys.INPUT_ERROR):
        return f"{text}\n\n{i18n.get(f'{key}-error')}"
    return text


async def main_getter(
    dialog_manager: DialogManager,
    services: Services,
    user: CurrentUser,
    i18n: TranslatorRunner,
    **_,
) -> dict:
    card = await load_card(dialog_manager, services, user)
    if card is None:
        return _data(i18n.get("expense-deleted"), **{PreviewDataKeys.CAN_EDIT: False})
    return _data(render.expense_text(card, i18n), **{PreviewDataKeys.CAN_EDIT: True})


def _prompt(key: str):
    """A getter for a window that shows one question (and the error line after a refusal)."""

    async def getter(
        dialog_manager: DialogManager,
        services: Services,
        user: CurrentUser,
        i18n: TranslatorRunner,
        **_,
    ) -> dict:
        card = await load_card(dialog_manager, services, user)
        if card is None:
            return _data(i18n.get("expense-deleted"))
        return _data(_with_error(i18n.get(key), key, dialog_manager, i18n))

    return getter


async def amount_getter(
    dialog_manager: DialogManager,
    services: Services,
    user: CurrentUser,
    i18n: TranslatorRunner,
    **_,
) -> dict:
    card = await load_card(dialog_manager, services, user)
    if card is None:
        return _data(i18n.get("expense-deleted"))
    key = "expense-edit-amount"
    text = i18n.get(key, amount=render.money(card.amount, i18n, card.currency))
    return _data(_with_error(text, key, dialog_manager, i18n))


async def tags_getter(
    dialog_manager: DialogManager,
    services: Services,
    user: CurrentUser,
    i18n: TranslatorRunner,
    **_,
) -> dict:
    card = await load_card(dialog_manager, services, user)
    if card is None:
        return _data(i18n.get("expense-deleted"))
    refused = bool(dialog_manager.dialog_data.get(DialogDataKeys.INPUT_ERROR))
    return tags.prompt_data(card.tags, i18n, refused=refused)


async def rename_getter(
    dialog_manager: DialogManager,
    services: Services,
    user: CurrentUser,
    i18n: TranslatorRunner,
    **_,
) -> dict:
    card = await load_card(dialog_manager, services, user)
    if card is None:
        return _data(i18n.get("expense-deleted"))
    key = "expense-edit-rename"
    text = i18n.get(key, name=escape(card.payment_source_name or ""))
    return _data(_with_error(text, key, dialog_manager, i18n))


async def payee_getter(
    dialog_manager: DialogManager,
    services: Services,
    user: CurrentUser,
    i18n: TranslatorRunner,
    **_,
) -> dict:
    card = await load_card(dialog_manager, services, user)
    if card is None:
        return _data(i18n.get("expense-deleted"))
    choices = await pickers.payee_choices(services, user.id, i18n, card.payee_key)
    return _data(i18n.get("entry-payee"), **{pickers.PickerData.PAYEES: choices})


async def source_getter(
    dialog_manager: DialogManager,
    services: Services,
    user: CurrentUser,
    i18n: TranslatorRunner,
    **_,
) -> dict:
    card = await load_card(dialog_manager, services, user)
    if card is None:
        return _data(i18n.get("expense-deleted"))
    current: str | None = None
    can_rename = False
    if card.payment_source_id is not None:
        sources = await services.expenses.payment_sources(user.id)
        source = next((s for s in sources if s.id == card.payment_source_id), None)
        if source is not None:
            is_cash = source.kind == "cash"
            current = pickers.CASH_ID if is_cash else str(source.id)
            can_rename = not is_cash
    choices = await pickers.source_choices(services, user.id, i18n, current)
    return _data(
        i18n.get("entry-source"),
        **{pickers.PickerData.SOURCES: choices, PreviewDataKeys.CAN_RENAME: can_rename},
    )


async def category_getter(
    dialog_manager: DialogManager,
    services: Services,
    user: CurrentUser,
    i18n: TranslatorRunner,
    **_,
) -> dict:
    card = await load_card(dialog_manager, services, user)
    if card is None:
        return _data(i18n.get("expense-deleted"))
    return _data(
        i18n.get("entry-category"),
        **{pickers.PickerData.CATEGORIES: pickers.category_choices(i18n, card.category)},
    )


payee_name_getter = _prompt("entry-payee-name")
new_card_getter = _prompt("entry-new-card")
date_getter = _prompt("entry-date")
date_text_getter = _prompt("entry-date-text")
