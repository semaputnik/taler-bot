"""Pickers shared by the dialogs that choose a payee, a payment source or a category.

Each picker is a widget factory (the buttons) plus a choices function (what a getter puts into
the window data). A button carries an id, never a name: a payee's id, a source's id (`cash` for
the cash source, which exists in the database only after its first use) or a category's name.
The click handler turns the id back into a value with the matching `resolve_*` function, so a
list that changed between the render and the tap is noticed instead of trusted.
"""

from aiogram_dialog.widgets.kbd import Group, Select
from aiogram_dialog.widgets.text import Format
from fluentogram import TranslatorRunner
from pydantic import BaseModel

from src.bot.handlers.dialog.receipt_card.common import EXPENSE_CATEGORIES
from src.services.container import Services
from src.services.results import PayeeOption, SourceOption

CASH_ID = "cash"


class PickerData:
    """Window-data keys of the pickers' choices."""

    PAYEES = "payees"
    SOURCES = "sources"
    CATEGORIES = "categories"


class Choice(BaseModel):
    """One button of a picker: `id` goes into the callback data, `text` is the label."""

    id: str
    text: str


def _select(id_: str, items: str, on_click, width: int) -> Group:
    return Group(
        Select(
            Format("{item.text}"),
            id=id_,
            item_id_getter=lambda choice: choice.id,
            items=items,
            on_click=on_click,
        ),
        width=width,
    )


def payee_select(on_click, id_: str = "payee") -> Group:
    return _select(id_, PickerData.PAYEES, on_click, width=1)


def source_select(on_click, id_: str = "source") -> Group:
    return _select(id_, PickerData.SOURCES, on_click, width=1)


def category_select(on_click, id_: str = "category") -> Group:
    return _select(id_, PickerData.CATEGORIES, on_click, width=2)


def _marked(text: str, current: bool, i18n: TranslatorRunner) -> str:
    return i18n.get("button-current", name=text) if current else text


async def payee_choices(
    services: Services, user_id: int, i18n: TranslatorRunner, current_key: str | None = None
) -> list[Choice]:
    """The user's most recently used payees; the one with `current_key` is marked."""
    options = await services.expenses.recent_payees(user_id)
    return [
        Choice(id=str(o.payee_id), text=_marked(o.name, o.payee_key == current_key, i18n))
        for o in options
    ]


async def resolve_payee(services: Services, user_id: int, item_id: str) -> PayeeOption | None:
    """The payee a tapped button stands for; None when it left the list meanwhile."""
    options = await services.expenses.recent_payees(user_id)
    return next((o for o in options if str(o.payee_id) == item_id), None)


async def source_choices(
    services: Services, user_id: int, i18n: TranslatorRunner, current_id: str | None = None
) -> list[Choice]:
    """Cash, then the user's cards by name; the source with `current_id` is marked."""
    cards = [s for s in await services.expenses.payment_sources(user_id) if s.kind != "cash"]
    named = [(CASH_ID, i18n.get("button-cash"))] + [(str(s.id), s.name) for s in cards]
    return [Choice(id=id_, text=_marked(text, id_ == current_id, i18n)) for id_, text in named]


async def resolve_source(services: Services, user_id: int, item_id: str) -> SourceOption | None:
    """The card a tapped button stands for; None for cash (use `CASH_ID`) or a card that left
    the list meanwhile."""
    sources = await services.expenses.payment_sources(user_id)
    return next((s for s in sources if str(s.id) == item_id and s.kind != "cash"), None)


def category_choices(i18n: TranslatorRunner, current: str | None = None) -> list[Choice]:
    """The twelve expense categories in list order; `current` is marked."""
    return [
        Choice(
            id=category,
            text=_marked(
                i18n.get(f"expense-category-{category.replace('_', '-')}"),
                category == current,
                i18n,
            ),
        )
        for category in EXPENSE_CATEGORIES
    ]
