"""Manual entry through the services on real Postgres: `ExpenseService.add_manual`, the edit
methods for the user's own facts, the pickers, and `CatalogService.add_card / rename_source`."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text

from src.database.repositories.expense import SqlAlchemyExpenseRepository
from src.domain.receipt import Receipt
from src.exception import (
    ExpenseFollowsReceipt,
    ExpenseNotFound,
    InvalidEdit,
    InvalidExpense,
    InvalidPaymentSource,
    UnknownPayee,
    UnknownPaymentSource,
    UserNotFound,
)
from src.services.catalog import CatalogService
from src.services.expense import ExpenseService
from src.services.results import ExpenseDraft, SourceOption
from tests.domain.builders import parse, photo, product
from tests.helpers import MakeUow, add_allowed_user, add_receipt, seed_catalog

D = Decimal
DAY = date(2026, 10, 16)


@pytest.fixture
async def service(make_uow: MakeUow) -> ExpenseService:
    await add_allowed_user(make_uow, 1)
    await add_allowed_user(make_uow, 2, username="bob")
    return ExpenseService(make_uow)


@pytest.fixture
def catalog_service(make_uow: MakeUow) -> CatalogService:
    return CatalogService(make_uow)


def draft(**fields) -> ExpenseDraft:
    args = {"amount": D("12.50"), "category": "restaurants", "spent_at": DAY, "cash": True} | fields
    return ExpenseDraft(**args)


async def catalog_of(make_uow: MakeUow, user_id: int = 1):
    async with make_uow() as uow:
        return await uow.catalog.get(user_id)


async def stored_expense(make_uow: MakeUow, expense_id: int):
    async with make_uow() as uow:
        expense = await uow.expenses.get(expense_id)
    assert expense is not None
    return expense


async def receipt_expense_id(make_uow: MakeUow, user_id: int = 1) -> int:
    bought = parse(product("mercadona::leche"), card_brand="VISA", card_last4="0848")
    await seed_catalog(make_uow, bought, user_id=user_id)
    receipt = Receipt.start(user_id, photo(f"r{user_id}"))
    receipt.apply_parse(bought)
    receipt = await add_receipt(make_uow, receipt, user_id=user_id)
    async with make_uow() as uow:
        expense = await uow.expenses.find_by_receipt(receipt.id)
    assert expense is not None and expense.id is not None
    return expense.id


# --- add_manual ----------------------------------------------------------------------------


async def test_add_manual_with_an_existing_payee_by_name_and_cash(service, make_uow):
    async with make_uow() as uow:
        catalog = await uow.catalog.get(1)
        catalog.ensure_payee("mercadona", "Mercadona")
        await uow.catalog.save(catalog)
        await uow.commit()

    card = await service.add_manual(
        1, draft(payee_name="  MERCADONA ", tags=["Holiday", "kids"], category="groceries")
    )

    assert (card.payee_name, card.payee_key, card.payment_source_name) == (
        "Mercadona",
        "mercadona",
        "Cash",
    )
    assert (card.amount, card.currency, card.spent_at) == (D("12.50"), "EUR", DAY)
    assert (card.category, card.tags, card.receipt_id) == ("groceries", ["holiday", "kids"], None)
    assert (card.can_edit_facts, card.deleted) == (True, False)
    catalog = await catalog_of(make_uow)
    assert list(catalog.payees) == ["mercadona"]  # reused, not duplicated
    assert card.payment_source_id == next(iter(catalog.payment_sources))
    stored = await stored_expense(make_uow, card.expense_id)
    assert (stored.payee_key, stored.payment_source_id) == ("mercadona", card.payment_source_id)


async def test_add_manual_with_a_new_payee_creates_it_by_the_slug_of_its_name(service, make_uow):
    card = await service.add_manual(1, draft(payee_name="Café Granja"))

    assert (card.payee_key, card.payee_name) == ("cafe-granja", "Café Granja")
    assert (await catalog_of(make_uow)).payees["cafe-granja"].name == "Café Granja"


async def test_add_manual_with_a_payee_key_picked_from_the_list(service, make_uow):
    first = await service.add_manual(1, draft(payee_name="Lidl"))

    card = await service.add_manual(1, draft(payee_key=first.payee_key))

    assert card.payee_name == "Lidl"
    assert len((await catalog_of(make_uow)).payees) == 1


async def test_add_manual_without_a_payee(service):
    card = await service.add_manual(1, draft())

    assert (card.payee_key, card.payee_name) == (None, None)


async def test_add_manual_with_cash_uses_the_users_one_cash_source(service, make_uow):
    first = await service.add_manual(1, draft())
    second = await service.add_manual(1, draft())

    assert first.payment_source_id == second.payment_source_id
    assert len((await catalog_of(make_uow)).payment_sources) == 1


async def test_add_manual_with_an_existing_card(service, make_uow, catalog_service):
    picked = await catalog_service.add_card(1, "Revolut")

    card = await service.add_manual(1, draft(cash=False, payment_source_id=picked.id))

    assert (card.payment_source_id, card.payment_source_name) == (picked.id, "Revolut")
    assert len((await catalog_of(make_uow)).payment_sources) == 1


async def test_add_manual_with_a_new_card_creates_it_before_the_expense(service, make_uow):
    card = await service.add_manual(1, draft(cash=False, new_card_name=" N26 "))

    catalog = await catalog_of(make_uow)
    [source] = catalog.payment_sources.values()
    assert (source.name, source.last4, source.brand) == ("N26", None, None)
    assert card.payment_source_id == source.id
    assert (await stored_expense(make_uow, card.expense_id)).payment_source_id == source.id


async def test_add_manual_without_a_source(service):
    card = await service.add_manual(1, draft(cash=False))

    assert (card.payment_source_id, card.payment_source_name) == (None, None)


async def test_add_manual_uses_the_users_default_currency(service, connection):
    await connection.execute(text("update users set default_currency = 'USD' where id = 1"))

    card = await service.add_manual(1, draft())

    assert (card.currency, (await service.add_manual(2, draft())).currency) == ("USD", "EUR")


@pytest.mark.parametrize("amount", ["0", "-5", "0.004"])
async def test_add_manual_refuses_an_amount_that_is_not_positive(service, amount):
    with pytest.raises(InvalidExpense):
        await service.add_manual(1, draft(amount=D(amount)))


async def test_a_failing_add_leaves_no_new_payee_or_card(service, make_uow):
    with pytest.raises(InvalidExpense):
        await service.add_manual(
            1, draft(amount=D("0"), cash=False, new_card_name="Revolut", payee_name="Lidl")
        )

    catalog = await catalog_of(make_uow)
    assert (catalog.payees, catalog.payment_sources) == ({}, {})


async def test_a_failure_while_storing_the_expense_rolls_the_catalog_back(
    service, make_uow, monkeypatch
):
    async def failing(self, expense):
        raise RuntimeError("boom")

    monkeypatch.setattr(SqlAlchemyExpenseRepository, "add", failing)

    with pytest.raises(RuntimeError):
        await service.add_manual(1, draft(cash=False, new_card_name="Revolut", payee_name="Lidl"))

    catalog = await catalog_of(make_uow)
    assert (catalog.payees, catalog.payment_sources) == ({}, {})


async def test_add_manual_refuses_an_unknown_category_payee_or_source(service, make_uow):
    with pytest.raises(InvalidEdit):
        await service.add_manual(1, draft(category="fruit_and_vegetables"))
    with pytest.raises(UnknownPayee):
        await service.add_manual(1, draft(payee_key="nobody"))
    with pytest.raises(UnknownPaymentSource):
        await service.add_manual(1, draft(cash=False, payment_source_id=987654))
    assert (await catalog_of(make_uow)).payment_sources == {}


async def test_add_manual_refuses_a_draft_that_names_two_payees_or_two_sources(service):
    with pytest.raises(InvalidEdit):
        await service.add_manual(1, draft(payee_key="lidl", payee_name="Lidl"))
    with pytest.raises(InvalidEdit):
        await service.add_manual(1, draft(new_card_name="N26"))  # cash is also set
    with pytest.raises(InvalidEdit):
        await service.add_manual(1, draft(cash=False, payment_source_id=1, new_card_name="N26"))


async def test_add_manual_refuses_another_users_source(service, make_uow, catalog_service):
    theirs = await catalog_service.add_card(2, "Theirs")

    with pytest.raises(UnknownPaymentSource):
        await service.add_manual(1, draft(cash=False, payment_source_id=theirs.id))


async def test_add_manual_refuses_a_new_card_name_in_use(service, catalog_service):
    await catalog_service.add_card(1, "Revolut")

    with pytest.raises(InvalidPaymentSource):
        await service.add_manual(1, draft(cash=False, new_card_name="revolut"))


async def test_add_manual_of_an_unknown_user_is_refused(service):
    with pytest.raises(UserNotFound):
        await service.add_manual(404, draft())


# --- the pickers ---------------------------------------------------------------------------


async def test_recent_payees_come_latest_first_five_by_default(service):
    for day, name in enumerate(["A", "B", "C", "D", "E", "F"], start=1):
        await service.add_manual(1, draft(payee_name=name, spent_at=date(2026, 10, day)))

    default = await service.recent_payees(1)
    two = await service.recent_payees(1, limit=2)

    assert [p.name for p in default] == ["F", "E", "D", "C", "B"]
    assert [p.payee_key for p in two] == ["f", "e"]
    assert await service.recent_payees(2) == []


async def test_payment_sources_are_cash_first_then_cards_by_name(
    service, catalog_service, make_uow
):
    await catalog_service.add_card(1, "revolut")
    await catalog_service.add_card(1, "Amex")
    await service.add_manual(1, draft())  # creates cash
    await catalog_service.add_card(2, "Theirs")

    options = await service.payment_sources(1)

    assert [(o.name, o.kind) for o in options] == [
        ("Cash", "cash"),
        ("Amex", "card"),
        ("revolut", "card"),
    ]
    assert all(isinstance(o, SourceOption) for o in options)


# --- CatalogService ------------------------------------------------------------------------


async def test_add_card_returns_the_option_and_persists_it(catalog_service, make_uow, service):
    option = await catalog_service.add_card(1, "  Revolut ")

    assert (option.name, option.kind) == ("Revolut", "card")
    assert (await catalog_of(make_uow)).payment_sources[option.id].name == "Revolut"
    assert await service.payment_sources(1) == [option]


async def test_add_card_refuses_an_empty_name_and_a_name_in_use(catalog_service, service):
    await catalog_service.add_card(1, "Revolut")

    with pytest.raises(InvalidPaymentSource):
        await catalog_service.add_card(1, "  ")
    with pytest.raises(InvalidPaymentSource):
        await catalog_service.add_card(1, "REVOLUT")
    assert len(await service.payment_sources(1)) == 1
    await catalog_service.add_card(2, "Revolut")  # names are per user


async def test_rename_source_renames_the_card_everywhere(catalog_service, service, make_uow):
    bought = parse(product("mercadona::leche"), card_brand="VISA", card_last4="0848")
    await seed_catalog(make_uow, bought)
    receipt = Receipt.start(1, photo())
    receipt.apply_parse(bought)
    await add_receipt(make_uow, receipt)
    [visa] = await service.payment_sources(1)

    option = await catalog_service.rename_source(1, visa.id, "  Family card ")

    assert option == SourceOption(id=visa.id, name="Family card", kind="card")
    assert [o.name for o in await service.payment_sources(1)] == ["Family card"]
    assert (await catalog_of(make_uow)).payment_sources[visa.id].last4 == "0848"  # digits stay
    async with make_uow() as uow:
        expense = await uow.expenses.find_by_receipt(receipt.id)
    assert (await service.card(1, expense.id)).payment_source_name == "Family card"


async def test_rename_source_refuses_an_empty_name_a_name_in_use_and_a_stranger(
    catalog_service, service
):
    first = await catalog_service.add_card(1, "Revolut")
    second = await catalog_service.add_card(1, "N26")
    theirs = await catalog_service.add_card(2, "Theirs")

    with pytest.raises(InvalidEdit):
        await catalog_service.rename_source(1, first.id, " ")
    with pytest.raises(InvalidPaymentSource):
        await catalog_service.rename_source(1, first.id, "n26")
    with pytest.raises(UnknownPaymentSource):
        await catalog_service.rename_source(1, theirs.id, "Mine")

    assert {o.name for o in await service.payment_sources(1)} == {"Revolut", "N26"}
    assert second.name == "N26"


# --- editing a manual expense --------------------------------------------------------------


async def manual_id(service: ExpenseService, **fields) -> int:
    return (await service.add_manual(1, draft(**fields))).expense_id


async def test_set_amount_persists_and_returns_the_card(service, make_uow):
    expense_id = await manual_id(service)

    card = await service.set_amount(1, expense_id, D("7.456"))

    assert card.amount == D("7.46")
    assert (await stored_expense(make_uow, expense_id)).amount == D("7.46")


async def test_set_amount_refuses_zero_and_changes_nothing(service):
    expense_id = await manual_id(service)

    with pytest.raises(InvalidExpense):
        await service.set_amount(1, expense_id, D("0"))

    assert (await service.card(1, expense_id)).amount == D("12.50")


async def test_set_payee_by_key_or_by_typed_name(service, make_uow):
    expense_id = await manual_id(service, payee_name="Lidl")
    other = await manual_id(service, payee_name="Aldi")

    by_key = await service.set_payee(1, other, payee_key="lidl")
    by_name = await service.set_payee(1, expense_id, payee_name=" Mercadona ")
    new = await service.set_payee(1, expense_id, payee_name="aldi")

    assert (by_key.payee_name, by_key.payee_key) == ("Lidl", "lidl")
    assert (by_name.payee_key, by_name.payee_name) == ("mercadona", "Mercadona")
    assert (new.payee_key, new.payee_name) == ("aldi", "Aldi")
    assert (await stored_expense(make_uow, expense_id)).payee_key == "aldi"


async def test_set_payee_needs_exactly_one_of_key_and_name_and_a_known_key(service):
    expense_id = await manual_id(service, payee_name="Lidl")

    with pytest.raises(InvalidEdit):
        await service.set_payee(1, expense_id)
    with pytest.raises(InvalidEdit):
        await service.set_payee(1, expense_id, payee_key="lidl", payee_name="Lidl")
    with pytest.raises(UnknownPayee):
        await service.set_payee(1, expense_id, payee_key="nobody")

    assert (await service.card(1, expense_id)).payee_key == "lidl"


async def test_set_source_to_a_card_cash_or_a_new_card(service, catalog_service, make_uow):
    expense_id = await manual_id(service, cash=False)
    revolut = await catalog_service.add_card(1, "Revolut")

    by_id = await service.set_source(1, expense_id, source_id=revolut.id)
    cash = await service.set_source(1, expense_id, cash=True)
    new = await service.set_source(1, expense_id, new_card_name="N26")

    assert (by_id.payment_source_id, by_id.payment_source_name) == (revolut.id, "Revolut")
    assert cash.payment_source_name == "Cash"
    assert new.payment_source_name == "N26"
    assert (await stored_expense(make_uow, expense_id)).payment_source_id == new.payment_source_id
    assert {o.name for o in await service.payment_sources(1)} == {"Cash", "Revolut", "N26"}


async def test_set_source_needs_exactly_one_choice_and_one_of_the_users_sources(
    service, catalog_service
):
    expense_id = await manual_id(service, cash=True)
    theirs = await catalog_service.add_card(2, "Theirs")

    with pytest.raises(InvalidEdit):
        await service.set_source(1, expense_id)
    with pytest.raises(InvalidEdit):
        await service.set_source(1, expense_id, cash=True, new_card_name="N26")
    with pytest.raises(UnknownPaymentSource):
        await service.set_source(1, expense_id, source_id=theirs.id)

    assert (await service.card(1, expense_id)).payment_source_name == "Cash"


async def test_set_date_persists_it(service, make_uow):
    expense_id = await manual_id(service)

    card = await service.set_date(1, expense_id, date(2026, 9, 30))

    assert card.spent_at == date(2026, 9, 30)
    assert (await stored_expense(make_uow, expense_id)).spent_at == date(2026, 9, 30)


async def test_a_receipt_expense_refuses_the_facts_the_receipt_owns_and_creates_nothing(
    service, catalog_service, make_uow
):
    expense_id = await receipt_expense_id(make_uow)
    before = await service.card(1, expense_id)
    assert before.can_edit_facts is False
    sources_before = await service.payment_sources(1)

    with pytest.raises(ExpenseFollowsReceipt):
        await service.set_amount(1, expense_id, D("1"))
    with pytest.raises(ExpenseFollowsReceipt):
        await service.set_payee(1, expense_id, payee_name="Brand new")
    with pytest.raises(ExpenseFollowsReceipt):
        await service.set_source(1, expense_id, new_card_name="Brand new")
    with pytest.raises(ExpenseFollowsReceipt):
        await service.set_date(1, expense_id, DAY)
    with pytest.raises(ExpenseFollowsReceipt):
        await service.soft_delete(1, expense_id)

    assert await service.card(1, expense_id) == before
    assert await service.payment_sources(1) == sources_before
    assert "brand-new" not in (await catalog_of(make_uow)).payees


async def test_the_category_and_tags_of_a_receipt_expense_stay_editable(service, make_uow):
    expense_id = await receipt_expense_id(make_uow)

    assert (await service.set_category(1, expense_id, "health")).category == "health"
    assert (await service.set_tags(1, expense_id, ["x"])).tags == ["x"]


async def test_the_edits_work_on_the_users_own_expense_only(service, catalog_service):
    theirs = (await service.add_manual(2, draft(payee_name="Lidl"))).expense_id

    with pytest.raises(ExpenseNotFound):
        await service.set_amount(1, theirs, D("1"))
    with pytest.raises(ExpenseNotFound):
        await service.set_payee(1, theirs, payee_name="x")
    with pytest.raises(ExpenseNotFound):
        await service.set_source(1, theirs, cash=True)
    with pytest.raises(ExpenseNotFound):
        await service.set_date(1, theirs, DAY)
    with pytest.raises(ExpenseNotFound):
        await service.soft_delete(1, theirs)
    assert (await service.card(2, theirs)).amount == D("12.50")


async def test_a_deleted_expense_refuses_the_edits(service):
    expense_id = await manual_id(service)
    await service.soft_delete(1, expense_id)

    with pytest.raises(InvalidExpense):
        await service.set_amount(1, expense_id, D("3"))
    with pytest.raises(InvalidExpense):
        await service.soft_delete(1, expense_id)


# --- delete, history, spending -------------------------------------------------------------


async def test_soft_delete_marks_the_expense_and_keeps_it_readable(service, make_uow):
    expense_id = await manual_id(service)

    card = await service.soft_delete(1, expense_id)

    assert card.deleted is True
    assert (await service.card(1, expense_id)).deleted is True
    assert (await stored_expense(make_uow, expense_id)).deleted_at is not None


async def test_history_and_spending_include_a_manual_expense_until_it_is_deleted(service):
    kept = await service.add_manual(
        1, draft(payee_name="Lidl", amount=D("30.00"), spent_at=date(2026, 10, 5))
    )
    gone = await manual_id(service, amount=D("5.00"), spent_at=date(2026, 10, 6))

    page = await service.history(1, 2026, 10)
    report = await service.spending(1, "month", date(2026, 10, 10))

    assert [(r.expense_id, r.has_receipt, r.receipt_id) for r in page.rows] == [
        (gone, False, None),
        (kept.expense_id, False, None),
    ]
    assert [r.payee_name for r in page.rows] == [None, "Lidl"]
    [block] = report.blocks
    assert (block.total, block.expense_count) == (D("35.00"), 2)
    assert [(a.label, a.value) for a in block.payees] == [("Lidl", D("30.00")), ("", D("5.00"))]
    assert [(a.key, a.value) for a in block.sources] == [("cash", D("35.00"))]
    assert {a.key for a in block.categories} == {"restaurants"}

    await service.soft_delete(1, gone)

    page = await service.history(1, 2026, 10)
    [block] = (await service.spending(1, "month", date(2026, 10, 10))).blocks
    assert [r.expense_id for r in page.rows] == [kept.expense_id]
    assert block.total == D("30.00")
