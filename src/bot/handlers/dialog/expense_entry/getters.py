from decimal import Decimal

from aiogram_dialog import DialogManager
from fluentogram import TranslatorRunner

from src.bot import render
from src.bot.handlers.dialog import pickers
from src.bot.handlers.dialog.expense_entry.common import DialogDataKeys, PreviewDataKeys
from src.services.container import Services
from src.services.results import CurrentUser


def _prompt(key: str, manager: DialogManager, user: CurrentUser, i18n: TranslatorRunner) -> str:
    """The amount on top, the question under it, and the error line after a refused input."""
    data = manager.dialog_data
    amount = render.money(Decimal(data[DialogDataKeys.AMOUNT]), i18n, user.default_currency)
    lines = [i18n.get("entry-amount", amount=amount), "", i18n.get(key)]
    if data.get(DialogDataKeys.INPUT_ERROR):
        lines += ["", i18n.get(f"{key}-error")]
    return "\n".join(lines)


def _text(text: str) -> dict:
    return {PreviewDataKeys.TEXT: text}


async def payee_getter(
    dialog_manager: DialogManager,
    services: Services,
    user: CurrentUser,
    i18n: TranslatorRunner,
    **_,
) -> dict:
    choices = await pickers.payee_choices(
        services, user.id, i18n, dialog_manager.dialog_data.get(DialogDataKeys.PAYEE_KEY)
    )
    return _text(_prompt("entry-payee", dialog_manager, user, i18n)) | {
        pickers.PickerData.PAYEES: choices
    }


async def payee_name_getter(
    dialog_manager: DialogManager, user: CurrentUser, i18n: TranslatorRunner, **_
) -> dict:
    return _text(_prompt("entry-payee-name", dialog_manager, user, i18n))


async def source_getter(
    dialog_manager: DialogManager,
    services: Services,
    user: CurrentUser,
    i18n: TranslatorRunner,
    **_,
) -> dict:
    choices = await pickers.source_choices(
        services, user.id, i18n, dialog_manager.dialog_data.get(DialogDataKeys.SOURCE)
    )
    return _text(_prompt("entry-source", dialog_manager, user, i18n)) | {
        pickers.PickerData.SOURCES: choices
    }


async def new_card_getter(
    dialog_manager: DialogManager, user: CurrentUser, i18n: TranslatorRunner, **_
) -> dict:
    return _text(_prompt("entry-new-card", dialog_manager, user, i18n))


async def category_getter(
    dialog_manager: DialogManager, user: CurrentUser, i18n: TranslatorRunner, **_
) -> dict:
    current = dialog_manager.dialog_data.get(DialogDataKeys.CATEGORY)
    return _text(_prompt("entry-category", dialog_manager, user, i18n)) | {
        pickers.PickerData.CATEGORIES: pickers.category_choices(i18n, current)
    }


async def date_getter(
    dialog_manager: DialogManager, user: CurrentUser, i18n: TranslatorRunner, **_
) -> dict:
    return _text(_prompt("entry-date", dialog_manager, user, i18n))


async def date_text_getter(
    dialog_manager: DialogManager, user: CurrentUser, i18n: TranslatorRunner, **_
) -> dict:
    return _text(_prompt("entry-date-text", dialog_manager, user, i18n))


async def tags_getter(
    dialog_manager: DialogManager, user: CurrentUser, i18n: TranslatorRunner, **_
) -> dict:
    return _text(_prompt("entry-tags", dialog_manager, user, i18n))
