"""`ExpenseRepository` through the Unit of Work, on real Postgres."""

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from src.domain.catalog import Catalog
from src.domain.enums import ExpenseCategory
from src.domain.expense import Expense
from src.domain.receipt import Receipt
from src.exception import (
    CheckViolationError,
    ForeignKeyViolationError,
    UniqueViolationError,
)
from tests.domain.builders import photo
from tests.helpers import MakeUow, add_receipt, add_user

D = Decimal


async def seed(make_uow: MakeUow, user_id: int = 1) -> int:
    """A user with a payee `landlord` and a card; returns the card's id."""
    await add_user(make_uow, user_id)
    catalog = Catalog(user_id=user_id)
    catalog.ensure_payee("landlord", "Landlord")
    catalog.ensure_card("VISA", "0848")
    async with make_uow() as uow:
        await uow.catalog.save(catalog)
        await uow.commit()
    [source_id] = [s.id for s in catalog.payment_sources.values()]
    assert source_id is not None
    return source_id


def rent(source_id: int | None = None, **fields) -> Expense:
    args = {
        "amount": D("850.00"),
        "currency": "EUR",
        "spent_at": date(2026, 10, 1),
        "category": ExpenseCategory.RENT,
        "payee_key": "landlord",
        "payment_source_id": source_id,
        "tags": ["Home", "monthly"],
    } | fields
    return Expense.start_manual(1, **args)


async def add(make_uow: MakeUow, expense: Expense) -> Expense:
    async with make_uow() as uow:
        expense = await uow.expenses.add(expense)
        await uow.commit()
    return expense


async def load(make_uow: MakeUow, expense_id: int) -> Expense | None:
    async with make_uow() as uow:
        return await uow.expenses.get(expense_id)


async def test_an_added_expense_loads_equal_with_its_tags(make_uow: MakeUow) -> None:
    source = await seed(make_uow)
    expense = await add(make_uow, rent(source))

    assert expense.id is not None and expense.created_at is not None
    assert await load(make_uow, expense.id) == expense
    assert expense.tags == ["home", "monthly"]
    assert expense.tags_changed is False


async def test_an_expense_without_payee_source_or_tags_round_trips(make_uow: MakeUow) -> None:
    await add_user(make_uow)
    expense = await add(
        make_uow, Expense.start_manual(1, amount=D("5"), currency="usd", spent_at=date(2026, 1, 2))
    )

    assert expense.id is not None
    loaded = await load(make_uow, expense.id)
    assert loaded == expense
    assert loaded is not None
    assert (loaded.payee_key, loaded.payment_source_id, loaded.tags) == (None, None, [])
    assert (loaded.currency, loaded.category) == ("USD", ExpenseCategory.OTHER)


async def test_get_returns_none_for_an_unknown_id(make_uow: MakeUow) -> None:
    await seed(make_uow)

    assert await load(make_uow, 987654) is None


async def test_find_by_receipt_returns_the_attached_expense(make_uow: MakeUow) -> None:
    await seed(make_uow)
    receipt = await add_receipt(make_uow, Receipt.start(1, photo()))
    assert receipt.id is not None
    backed = Expense(
        user_id=1,
        amount=D("12.00"),
        currency="EUR",
        spent_at=date(2026, 10, 14),
        category=ExpenseCategory.GROCERIES,
        receipt_id=receipt.id,
    )
    backed = await add(make_uow, backed)
    await add(make_uow, rent())

    async with make_uow() as uow:
        found = await uow.expenses.find_by_receipt(receipt.id)
        assert await uow.expenses.find_by_receipt(receipt.id + 1000) is None
    assert found == backed


async def test_a_receipt_has_at_most_one_expense(make_uow: MakeUow) -> None:
    await seed(make_uow)
    receipt = await add_receipt(make_uow, Receipt.start(1, photo()))
    assert receipt.id is not None
    twin = Expense(
        user_id=1, amount=D("1"), currency="EUR", spent_at=date(2026, 10, 14), receipt_id=receipt.id
    )
    await add(make_uow, twin)

    async with make_uow() as uow:
        with pytest.raises(UniqueViolationError):
            await uow.expenses.add(replace(twin))


async def test_save_updates_the_row_and_rewrites_the_tags(make_uow: MakeUow) -> None:
    source = await seed(make_uow)
    expense = await add(make_uow, rent())
    assert expense.id is not None

    async with make_uow() as uow:
        loaded = await uow.expenses.get(expense.id)
        assert loaded is not None
        loaded.set_amount(D("900"))
        loaded.set_source(source)
        loaded.set_date(date(2026, 11, 1))
        loaded.set_category(ExpenseCategory.UTILITIES)
        loaded.set_tags(["monthly", "bills"])
        await uow.expenses.save(loaded)
        assert loaded.tags_changed is False
        await uow.commit()

    after = await load(make_uow, expense.id)
    assert after is not None
    assert (after.amount, after.payment_source_id, after.spent_at) == (
        D("900.00"),
        source,
        date(2026, 11, 1),
    )
    assert (after.category, after.tags) == (ExpenseCategory.UTILITIES, ["bills", "monthly"])


async def test_save_without_a_tag_change_leaves_the_tags_alone(
    make_uow: MakeUow, statements: list[str]
) -> None:
    await seed(make_uow)
    expense = await add(make_uow, rent())
    assert expense.id is not None

    async with make_uow() as uow:
        loaded = await uow.expenses.get(expense.id)
        assert loaded is not None
        loaded.set_category(ExpenseCategory.OTHER)
        statements.clear()
        await uow.expenses.save(loaded)

    assert not [s for s in statements if "expense_tags" in s or "INSERT INTO tags" in s]


async def test_clearing_the_tags_removes_the_links_but_keeps_the_tag_rows(
    make_uow: MakeUow, connection: AsyncConnection
) -> None:
    await seed(make_uow)
    expense = await add(make_uow, rent())
    assert expense.id is not None

    async with make_uow() as uow:
        loaded = await uow.expenses.get(expense.id)
        assert loaded is not None
        loaded.set_tags([])
        await uow.expenses.save(loaded)
        await uow.commit()

    after = await load(make_uow, expense.id)
    assert after is not None and after.tags == []
    names = (await connection.execute(text("SELECT name FROM tags ORDER BY name"))).scalars()
    assert list(names) == ["home", "monthly"]


async def test_expenses_of_a_user_share_one_tag_row_per_name(
    make_uow: MakeUow, connection: AsyncConnection
) -> None:
    await seed(make_uow)
    await add_user(make_uow, 2)
    first = await add(make_uow, rent(tags=["holiday"]))
    second = await add(make_uow, rent(tags=["holiday", "kids"]))
    other_user = await add(
        make_uow, Expense.start_manual(2, amount=D("1"), currency="EUR", spent_at=date(2026, 1, 1))
    )
    other_user.set_tags(["holiday"])
    async with make_uow() as uow:
        await uow.expenses.save(other_user)
        await uow.commit()
    counts = (
        await connection.execute(
            text("SELECT user_id, name, count(*) FROM tags GROUP BY 1, 2 ORDER BY 1, 2")
        )
    ).all()

    assert [tuple(r) for r in counts] == [(1, "holiday", 1), (1, "kids", 1), (2, "holiday", 1)]
    assert first.id != second.id


async def test_a_soft_deleted_expense_loads_with_its_deletion_time(make_uow: MakeUow) -> None:
    await seed(make_uow)
    expense = await add(make_uow, rent())
    assert expense.id is not None
    when = datetime(2026, 10, 15, 8, 0, tzinfo=UTC)

    async with make_uow() as uow:
        loaded = await uow.expenses.get(expense.id)
        assert loaded is not None
        loaded.soft_delete(when)
        await uow.expenses.save(loaded)
        await uow.commit()

    after = await load(make_uow, expense.id)
    assert after is not None and after.deleted_at == when


async def test_an_unknown_payee_is_refused(make_uow: MakeUow) -> None:
    await seed(make_uow)

    async with make_uow() as uow:
        with pytest.raises(ForeignKeyViolationError):
            await uow.expenses.add(rent(payee_key="nobody"))


async def test_another_users_payee_and_source_are_refused(make_uow: MakeUow) -> None:
    await seed(make_uow, 1)
    theirs = await seed(make_uow, 2)  # user 2 has the same payee key and a card too

    async with make_uow() as uow:
        with pytest.raises(ForeignKeyViolationError):
            await uow.expenses.add(rent(payment_source_id=theirs))
    mine = await add(make_uow, rent())
    assert mine.id is not None
    mine.set_source(theirs)
    async with make_uow() as uow:
        with pytest.raises(ForeignKeyViolationError):
            await uow.expenses.save(mine)


async def test_the_payee_is_resolved_for_the_expenses_user(
    make_uow: MakeUow, connection: AsyncConnection
) -> None:
    await seed(make_uow, 1)
    await seed(make_uow, 2)  # both own a payee `landlord`, with different ids
    expense = await add(make_uow, Expense.start_manual(2, **_rent_args()))

    assert expense.id is not None
    assert (await load(make_uow, expense.id)).payee_key == "landlord"  # type: ignore[union-attr]
    async with make_uow() as uow:
        theirs = (await uow.catalog.get(2)).payees["landlord"].id
    row = (
        await connection.execute(
            text("SELECT payee_id FROM expenses WHERE id = :id"), {"id": expense.id}
        )
    ).scalar_one()
    assert row == theirs


def _rent_args() -> dict:
    return {
        "amount": D("1"),
        "currency": "EUR",
        "spent_at": date(2026, 10, 1),
        "payee_key": "landlord",
    }


# --- constraints ------------------------------------------------------------------------


async def test_the_database_refuses_an_unknown_category(make_uow: MakeUow) -> None:
    await seed(make_uow)
    expense = rent()
    expense.category = "nonsense"  # type: ignore[assignment]

    async with make_uow() as uow:
        with pytest.raises(CheckViolationError):
            await uow.expenses.add(expense)


async def test_the_database_refuses_a_negative_amount(make_uow: MakeUow) -> None:
    await seed(make_uow)
    expense = rent()
    expense.amount = D("-1")  # bypasses the aggregate on purpose

    async with make_uow() as uow:
        with pytest.raises(CheckViolationError):
            await uow.expenses.add(expense)


@pytest.mark.parametrize("name", ["", "x" * 33])
async def test_the_database_refuses_a_tag_name_of_the_wrong_length(
    make_uow: MakeUow, connection: AsyncConnection, name: str
) -> None:
    await add_user(make_uow)

    with pytest.raises(CheckViolationError):
        async with connection.begin_nested():
            await connection.execute(
                text("INSERT INTO tags (user_id, name) VALUES (1, :name)"), {"name": name}
            )


async def test_deleting_a_payment_source_keeps_the_expense_without_it(
    make_uow: MakeUow, connection: AsyncConnection
) -> None:
    source = await seed(make_uow)
    expense = await add(make_uow, rent(source))
    assert expense.id is not None

    await connection.execute(text("DELETE FROM payment_sources WHERE id = :id"), {"id": source})

    after = await load(make_uow, expense.id)
    assert after is not None and after.payment_source_id is None


async def test_deleting_a_user_removes_expenses_tags_and_links(
    make_uow: MakeUow, connection: AsyncConnection
) -> None:
    source = await seed(make_uow)
    await add(make_uow, rent(source))

    async with make_uow() as uow:
        await uow.users.delete(1)
        await uow.commit()
    left = (
        await connection.execute(
            text(
                "SELECT (SELECT count(*) FROM expenses), (SELECT count(*) FROM tags),"
                " (SELECT count(*) FROM expense_tags), (SELECT count(*) FROM payment_sources)"
            )
        )
    ).one()
    assert tuple(left) == (0, 0, 0, 0)


# --- the payees used most recently -----------------------------------------------------------


async def spend(make_uow: MakeUow, payee_key: str | None, day: int, *, user_id: int = 1) -> Expense:
    return await add(
        make_uow,
        Expense.start_manual(
            user_id,
            amount=D("5"),
            currency="EUR",
            spent_at=date(2026, 10, day),
            payee_key=payee_key,
        ),
    )


async def payees_seeded(make_uow: MakeUow, *names: str, user_id: int = 1) -> None:
    await add_user(make_uow, user_id)
    catalog = Catalog(user_id=user_id)
    for name in names:
        catalog.ensure_payee_named(name)
    async with make_uow() as uow:
        await uow.catalog.save(catalog)
        await uow.commit()


async def test_recent_payees_are_ordered_by_their_latest_expense_then_by_name(
    make_uow: MakeUow,
) -> None:
    await payees_seeded(make_uow, "Lidl", "Aldi", "Mercadona", "Zara", "Never used")
    await spend(make_uow, "lidl", 3)
    await spend(make_uow, "lidl", 9)  # Lidl's latest
    await spend(make_uow, "mercadona", 5)
    await spend(make_uow, "aldi", 5)  # same day as Mercadona: by name
    await spend(make_uow, "zara", 1)
    await spend(make_uow, None, 20)  # an expense without a payee counts for nobody

    async with make_uow() as uow:
        found = await uow.expenses.recent_payees(1, 10)

    assert [(p.payee_key, p.name) for p in found] == [
        ("lidl", "Lidl"),
        ("aldi", "Aldi"),
        ("mercadona", "Mercadona"),
        ("zara", "Zara"),
    ]
    assert all(p.payee_id > 0 for p in found)


async def test_recent_payees_stop_at_the_limit(make_uow: MakeUow) -> None:
    await payees_seeded(make_uow, "A", "B", "C")
    for day, key in enumerate(("a", "b", "c"), start=1):
        await spend(make_uow, key, day)

    async with make_uow() as uow:
        assert [p.payee_key for p in await uow.expenses.recent_payees(1, 2)] == ["c", "b"]
        assert await uow.expenses.recent_payees(1, 0) == []


async def test_a_deleted_expense_does_not_make_a_payee_recent(make_uow: MakeUow) -> None:
    await payees_seeded(make_uow, "Lidl", "Aldi")
    await spend(make_uow, "lidl", 3)
    newer = await spend(make_uow, "aldi", 9)
    newer.soft_delete()
    async with make_uow() as uow:
        await uow.expenses.save(newer)
        await uow.commit()

    async with make_uow() as uow:
        assert [p.payee_key for p in await uow.expenses.recent_payees(1, 5)] == ["lidl"]


async def test_recent_payees_are_per_user(make_uow: MakeUow) -> None:
    await payees_seeded(make_uow, "Lidl", user_id=1)
    await payees_seeded(make_uow, "Lidl", "Aldi", user_id=2)
    await spend(make_uow, "lidl", 3)
    await spend(make_uow, "aldi", 4, user_id=2)

    async with make_uow() as uow:
        assert [p.payee_key for p in await uow.expenses.recent_payees(1, 5)] == ["lidl"]
        assert [p.payee_key for p in await uow.expenses.recent_payees(2, 5)] == ["aldi"]
