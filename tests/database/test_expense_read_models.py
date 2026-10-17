"""The expense repository's read models (`history`, `spending`, `earliest_spent_at`) on real
Postgres. Receipts come with their expenses, as the app makes them (`tests.helpers.add_receipt`)."""

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from itertools import count

import pytest

from src.database.read_models import (
    Amount,
    CurrencyBlock,
    CurrencyTotal,
    HistoryPage,
    HistoryRow,
    SpendingPeriod,
)
from src.domain.enums import ExpenseCategory, ProductCategory
from src.domain.expense import Expense
from src.domain.receipt import Receipt
from tests.domain.builders import parse, photo, product
from tests.helpers import MakeUow, add_receipt, add_user, seed_catalog

D = Decimal
MADRID = "Europe/Madrid"
SPENDING_STATEMENTS = 5  # totals, expense categories, product categories, payees, sources
HISTORY_STATEMENTS = 4  # rows, aggregates, totals per currency, the month's payees
_ids = count(1)


def at(day: int, hour: int = 12, *, month: int = 10, year: int = 2026) -> datetime:
    return datetime(year, month, day, hour, 0, tzinfo=UTC)


async def bought(
    make_uow: MakeUow,
    purchased_at: datetime,
    *lines: tuple[ProductCategory, str],
    store: str = "mercadona",
    total: str | None = None,
    currency: str = "EUR",
    card: tuple[str | None, str] | None = None,
    deleted: bool = False,
    duplicate_of: int | None = None,
    user_id: int = 1,
) -> Receipt:
    """A stored parsed receipt of the user whose item lines are `(category, amount)` (one 10.00
    line without any); the total is the lines' sum unless given. It gets its expense, which is
    deleted with it."""
    n = next(_ids)
    lines = lines or ((ProductCategory.DAIRY, "10.00"),)
    items = tuple(
        product(f"{store}::item{n}-{i}", total=amount, category=category)
        for i, (category, amount) in enumerate(lines)
    )
    amount = total if total is not None else str(sum((D(a) for _, a in lines), D(0)))
    one = parse(
        *items,
        store_key=store,
        store_name=store.capitalize(),
        purchased_at=purchased_at,
        receipt_number=str(n),
        receipt_key=f"{store}|{n}",
        total=D(amount),
        currency=currency,
        card_brand=card[0] if card else None,
        card_last4=card[1] if card else None,
    )
    await add_user(make_uow, user_id)
    await seed_catalog(make_uow, one, user_id=user_id)
    receipt = Receipt.start(user_id, photo(f"r{user_id}-{n}"))
    receipt.apply_parse(one)
    if duplicate_of is not None:
        receipt.mark_duplicate(duplicate_of)
    if deleted:
        receipt.soft_delete()
    return await add_receipt(make_uow, receipt, user_id=user_id)


async def typed(
    make_uow: MakeUow,
    day: date,
    amount: str = "20.00",
    *,
    category: ExpenseCategory = ExpenseCategory.RENT,
    payee: str | None = None,
    currency: str = "EUR",
    user_id: int = 1,
) -> Expense:
    """An expense typed by hand: no receipt behind it."""
    await add_user(make_uow, user_id)
    async with make_uow() as uow:
        if payee is not None:
            catalog = await uow.catalog.get(user_id)
            catalog.ensure_payee(payee, payee.capitalize())
            await uow.catalog.save(catalog)
        expense = await uow.expenses.add(
            Expense.start_manual(
                user_id,
                amount=D(amount),
                currency=currency,
                spent_at=day,
                category=category,
                payee_key=payee,
            )
        )
        await uow.commit()
    return expense


async def expense_id_of(make_uow: MakeUow, receipt: Receipt) -> int:
    async with make_uow() as uow:
        expense = await uow.expenses.find_by_receipt(receipt.id)
    assert expense is not None and expense.id is not None
    return expense.id


async def october(make_uow: MakeUow, *, user_id: int = 1, **kwargs) -> HistoryPage:
    async with make_uow() as uow:
        return await uow.expenses.history(user_id, 2026, 10, MADRID, **kwargs)


async def payee_id_of(make_uow: MakeUow, key: str) -> int:
    async with make_uow() as uow:
        return (await uow.catalog.get(1)).payees[key].id


# --- history ---------------------------------------------------------------------------------


async def test_an_expense_lands_in_the_month_of_its_spent_at_day(make_uow):
    inside = await bought(make_uow, at(10))
    await bought(make_uow, at(10, month=9))
    await bought(make_uow, at(10, month=11))

    page = await october(make_uow)

    assert [r.receipt_id for r in page.rows] == [inside.id]
    assert (page.year, page.month, page.total_rows, page.expense_count) == (2026, 10, 1, 1)


async def test_the_day_is_the_users_local_day_of_the_purchase(make_uow):
    # 23:30 UTC on 31 October is 00:30 on 1 November in Madrid (UTC+1 after the clock change).
    late = await bought(make_uow, datetime(2026, 10, 31, 23, 30, tzinfo=UTC))
    kept = await bought(make_uow, datetime(2026, 10, 31, 22, 30, tzinfo=UTC))

    november = await _history(make_uow, 2026, 11)
    october_page = await october(make_uow)

    assert [(r.receipt_id, r.day) for r in october_page.rows] == [(kept.id, date(2026, 10, 31))]
    assert [(r.receipt_id, r.day) for r in november.rows] == [(late.id, date(2026, 11, 1))]


async def _history(make_uow: MakeUow, year: int, month: int) -> HistoryPage:
    async with make_uow() as uow:
        return await uow.expenses.history(1, year, month, MADRID)


async def test_a_receipt_row_carries_the_receipt_the_payee_the_amount_and_the_status(make_uow):
    one = await bought(make_uow, at(10), store="lidl", total="23.10", currency="USD")

    (row,) = (await october(make_uow)).rows

    assert row == HistoryRow(
        expense_id=await expense_id_of(make_uow, one),
        receipt_id=one.id,
        has_receipt=True,
        day=date(2026, 10, 10),
        payee_name="Lidl",
        amount=D("23.10"),
        currency="USD",
        category="groceries",
        status="parsed",
    )


async def test_a_row_without_a_receipt_has_no_receipt_and_no_status(make_uow):
    rent = await typed(make_uow, date(2026, 10, 1), "850.00", payee="landlord")

    (row,) = (await october(make_uow)).rows

    assert row == HistoryRow(
        expense_id=rent.id,
        receipt_id=None,
        has_receipt=False,
        day=date(2026, 10, 1),
        payee_name="Landlord",
        amount=D("850.00"),
        currency="EUR",
        category="rent",
        status=None,
    )


async def test_receipts_and_typed_expenses_share_the_month(make_uow):
    one = await bought(make_uow, at(10), total="10.00")
    rent = await typed(make_uow, date(2026, 10, 12), "850.00")

    page = await october(make_uow)

    assert [(r.expense_id, r.has_receipt) for r in page.rows] == [
        (rent.id, False),
        (await expense_id_of(make_uow, one), True),
    ]
    assert page.totals == [CurrencyTotal(currency="EUR", amount=D("860.00"))]


async def test_deleted_expenses_are_left_out_of_rows_counts_totals_and_payees(make_uow):
    kept = await bought(make_uow, at(10), store="lidl", total="5.00")
    await bought(make_uow, at(11), store="aldi", total="7.00", deleted=True)
    await bought(make_uow, at(12, month=9), deleted=True)
    await bought(make_uow, at(12, month=11), deleted=True)

    page = await october(make_uow)

    assert [r.receipt_id for r in page.rows] == [kept.id]
    assert page.total_rows == 1
    assert page.totals == [CurrencyTotal(currency="EUR", amount=D("5.00"))]
    assert [p.name for p in page.payees] == ["Lidl"]
    assert (page.has_earlier, page.has_later) == (False, False)


async def unread(
    make_uow: MakeUow,
    received_at: datetime,
    *,
    status: str = "failed",
    deleted: bool = False,
    user_id: int = 1,
) -> Receipt:
    """A stored receipt that is not a purchase: it has no expense."""
    await add_user(make_uow, user_id)
    receipt = Receipt.start(user_id, replace(photo(f"u{next(_ids)}"), received_at=received_at))
    if status == "failed":
        receipt.mark_parsing()
        receipt.mark_failed("timeout")
    elif status == "parsing":
        receipt.mark_parsing()
    if deleted:
        receipt.soft_delete()
    return await add_receipt(make_uow, receipt, user_id=user_id)


async def test_a_receipt_without_an_expense_is_a_row_of_its_month_with_its_status(make_uow):
    original = await bought(make_uow, at(4, month=9))
    duplicate = await bought(make_uow, at(4), duplicate_of=original.id)
    failed = await unread(make_uow, at(5))
    pending = await unread(make_uow, at(6), status="pending")
    parsing = await unread(make_uow, at(7), status="parsing")

    page = await october(make_uow)

    assert [(r.receipt_id, r.status) for r in page.rows] == [
        (parsing.id, "parsing"),
        (pending.id, "pending"),
        (failed.id, "failed"),
        (duplicate.id, "duplicate"),
    ]
    assert all(r.expense_id is None and r.has_receipt for r in page.rows)
    assert all(r.amount is None and r.currency is None and r.category is None for r in page.rows)
    assert (page.total_rows, page.expense_count) == (4, 0)
    assert page.totals == []


async def test_a_receipt_row_without_an_expense_shows_the_payee_of_its_parse(make_uow):
    original = await bought(make_uow, at(4, month=9), store="lidl")
    duplicate = await bought(make_uow, at(4), store="lidl", duplicate_of=original.id)

    (row,) = (await october(make_uow)).rows

    assert (row.receipt_id, row.payee_name, row.day) == (duplicate.id, "Lidl", date(2026, 10, 4))


async def test_a_receipt_without_an_expense_is_placed_by_its_purchase_or_photo_time_locally(
    make_uow,
):
    # No purchase time: the photo's received_at, in the user's time zone (00:30 on 1 November).
    late = await unread(make_uow, datetime(2026, 10, 31, 23, 30, tzinfo=UTC))
    kept = await unread(make_uow, datetime(2026, 10, 31, 22, 30, tzinfo=UTC))

    november = await _history(make_uow, 2026, 11)
    october_page = await october(make_uow)

    assert [(r.receipt_id, r.day) for r in october_page.rows] == [(kept.id, date(2026, 10, 31))]
    assert [(r.receipt_id, r.day) for r in november.rows] == [(late.id, date(2026, 11, 1))]


async def test_deleted_receipts_without_an_expense_are_left_out(make_uow):
    kept = await unread(make_uow, at(5))
    await unread(make_uow, at(6), deleted=True)

    page = await october(make_uow)

    assert [r.receipt_id for r in page.rows] == [kept.id]
    assert page.total_rows == 1


async def test_receipt_rows_and_expense_rows_mix_newest_day_first_expenses_first_on_a_day(
    make_uow,
):
    old = await bought(make_uow, at(3))
    failed = await unread(make_uow, at(9))
    same_day = await bought(make_uow, at(9))
    typed_later = await typed(make_uow, date(2026, 10, 20))

    page = await october(make_uow)

    assert [(r.expense_id, r.receipt_id) for r in page.rows] == [
        (typed_later.id, None),
        (await expense_id_of(make_uow, same_day), same_day.id),
        (None, failed.id),
        (await expense_id_of(make_uow, old), old.id),
    ]
    assert (page.total_rows, page.expense_count) == (4, 3)
    assert page.totals == [CurrencyTotal(currency="EUR", amount=D("40.00"))]


async def test_the_payee_filter_applies_to_receipt_rows_without_an_expense_too(make_uow):
    shop = await bought(make_uow, at(1, month=9), store="lidl")
    other = await bought(make_uow, at(1, month=9), store="aldi")
    kept = await bought(make_uow, at(4), store="lidl", duplicate_of=shop.id)
    await bought(make_uow, at(5), store="aldi", duplicate_of=other.id)
    await unread(make_uow, at(6))
    lidl = await payee_id_of(make_uow, "lidl")

    page = await october(make_uow, payee_id=lidl)

    assert [r.receipt_id for r in page.rows] == [kept.id]
    assert (page.total_rows, page.payee_name) == (1, "Lidl")
    assert sorted(p.name for p in page.payees) == ["Aldi", "Lidl"]


async def test_has_earlier_and_has_later_count_receipts_without_an_expense(make_uow):
    await bought(make_uow, at(10))
    await unread(make_uow, at(20, month=8))
    await unread(make_uow, at(2, month=12))

    page = await october(make_uow)

    assert (page.has_earlier, page.has_later) == (True, True)


async def test_another_users_receipts_without_an_expense_are_never_shown(make_uow):
    await unread(make_uow, at(5))
    await add_user(make_uow, 2)

    assert (await october(make_uow, user_id=2)).rows == []


async def test_rows_are_newest_day_first_with_the_id_breaking_ties(make_uow):
    old = await bought(make_uow, at(3))
    same_first = await bought(make_uow, at(9))
    same_second = await bought(make_uow, at(9))
    typed_later = await typed(make_uow, date(2026, 10, 20))

    page = await october(make_uow)

    assert [r.expense_id for r in page.rows] == [
        typed_later.id,
        await expense_id_of(make_uow, same_second),
        await expense_id_of(make_uow, same_first),
        await expense_id_of(make_uow, old),
    ]


async def test_offset_and_limit_page_the_rows_and_total_rows_counts_them_all(make_uow):
    made = [await bought(make_uow, at(day)) for day in range(1, 6)]
    newest_first = [r.id for r in reversed(made)]

    first = await october(make_uow, offset=0, limit=2)
    last = await october(make_uow, offset=4, limit=2)
    past = await october(make_uow, offset=10, limit=2)

    assert [r.receipt_id for r in first.rows] == newest_first[:2]
    assert [r.receipt_id for r in last.rows] == newest_first[4:]
    assert (past.rows, past.total_rows) == ([], 5)
    assert first.total_rows == last.total_rows == 5


async def test_totals_are_one_entry_per_currency(make_uow):
    await bought(make_uow, at(1), total="10.00")
    await bought(make_uow, at(2), total="5.50")
    await bought(make_uow, at(3), total="8.00", currency="USD")

    page = await october(make_uow)

    assert page.totals == [
        CurrencyTotal(currency="EUR", amount=D("15.50")),
        CurrencyTotal(currency="USD", amount=D("8.00")),
    ]


async def test_the_payee_filter_narrows_rows_counts_and_totals_but_not_the_payees(make_uow):
    await bought(make_uow, at(1), store="lidl", total="10.00")
    await bought(make_uow, at(2), store="lidl", total="2.00")
    await bought(make_uow, at(3), store="aldi", total="7.00")
    lidl = await payee_id_of(make_uow, "lidl")

    page = await october(make_uow, payee_id=lidl)

    assert {r.payee_name for r in page.rows} == {"Lidl"}
    assert page.total_rows == 2
    assert page.totals == [CurrencyTotal(currency="EUR", amount=D("12.00"))]
    assert page.payee_name == "Lidl"
    assert [p.name for p in page.payees] == ["Aldi", "Lidl"]
    assert page.payees[1].payee_id == lidl


async def test_the_payees_are_those_with_an_expense_in_the_month(make_uow):
    await bought(make_uow, at(1), store="lidl")
    await bought(make_uow, at(2), store="lidl")
    await bought(make_uow, at(3, month=9), store="aldi")

    page = await october(make_uow)

    assert [p.name for p in page.payees] == ["Lidl"]
    assert page.payee_name is None


async def test_a_payee_that_is_not_the_users_matches_nothing(make_uow):
    await bought(make_uow, at(1))

    page = await october(make_uow, payee_id=987654)

    assert (page.rows, page.total_rows, page.totals) == ([], 0, [])
    assert page.payee_name is None
    assert len(page.payees) == 1


async def test_has_earlier_and_has_later_look_for_any_expense_outside_the_month(make_uow):
    await bought(make_uow, at(10))

    assert (await october(make_uow)).has_earlier is False
    assert (await october(make_uow)).has_later is False

    await bought(make_uow, at(20, month=8))
    await typed(make_uow, date(2026, 12, 2))

    page = await october(make_uow)
    assert (page.has_earlier, page.has_later) == (True, True)
    august = await _history(make_uow, 2026, 8)
    december = await _history(make_uow, 2026, 12)
    assert (august.has_earlier, august.has_later) == (False, True)
    assert (december.has_earlier, december.has_later) == (True, False)


async def test_another_users_expenses_are_never_shown(make_uow):
    await bought(make_uow, at(10))
    await add_user(make_uow, 2)

    page = await october(make_uow, user_id=2)

    assert (page.rows, page.total_rows, page.payees) == ([], 0, [])
    assert (page.has_earlier, page.has_later) == (False, False)


async def test_an_empty_month_is_an_empty_page(make_uow):
    await add_user(make_uow)

    page = await october(make_uow)

    assert page == HistoryPage(
        year=2026,
        month=10,
        rows=[],
        total_rows=0,
        expense_count=0,
        totals=[],
        payees=[],
        has_earlier=False,
        has_later=False,
        payee_name=None,
    )


@pytest.mark.parametrize("size", [3, 30])
async def test_history_runs_the_same_statements_whatever_the_month_size(make_uow, statements, size):
    for n in range(size):
        await bought(make_uow, at(1 + n % 28), store=f"shop{n % 4}")
        await unread(make_uow, at(1 + n % 28))
    shop = await payee_id_of(make_uow, "shop1")
    statements.clear()

    await october(make_uow, payee_id=shop, limit=8)

    assert len([s for s in statements if s.startswith("SELECT")]) == HISTORY_STATEMENTS


# --- spending --------------------------------------------------------------------------------


async def october_spending(make_uow: MakeUow, *, user_id: int = 1) -> SpendingPeriod:
    async with make_uow() as uow:
        return await uow.expenses.spending(user_id, date(2026, 10, 1), date(2026, 11, 1))


def only_block(period: SpendingPeriod) -> CurrencyBlock:
    [block] = period.blocks
    return block


async def test_spending_membership_is_the_spent_at_day(make_uow):
    await bought(make_uow, at(10), (ProductCategory.DAIRY, "5.00"))
    # 23:30 UTC on the last day of October is already 00:30 on 1 November in Madrid.
    await bought(make_uow, at(31, 23), (ProductCategory.DAIRY, "7.00"), store="late")
    # 23:30 UTC on 30 September is 01:30 on 1 October in Madrid (CEST, UTC+2).
    await bought(
        make_uow,
        datetime(2026, 9, 30, 23, 30, tzinfo=UTC),
        (ProductCategory.PANTRY, "3.00"),
        store="e",
    )
    await bought(make_uow, at(10, month=9), (ProductCategory.DAIRY, "100.00"))
    await typed(make_uow, date(2026, 10, 31), "4.00")
    await typed(make_uow, date(2026, 11, 1), "40.00")

    block = only_block(await october_spending(make_uow))

    assert (block.total, block.expense_count) == (D("12.00"), 3)


async def test_spending_counts_only_not_deleted_expenses(make_uow):
    await bought(make_uow, at(2), (ProductCategory.DAIRY, "5.00"))
    await bought(make_uow, at(3), (ProductCategory.DAIRY, "50.00"), deleted=True)
    first = await bought(make_uow, at(4), (ProductCategory.DAIRY, "60.00"), store="dup")
    assert first.id is not None
    await bought(make_uow, at(5), (ProductCategory.DAIRY, "70.00"), duplicate_of=first.id)
    gone = await typed(make_uow, date(2026, 10, 6), "9.00")
    async with make_uow() as uow:
        expense = await uow.expenses.get(gone.id)
        expense.soft_delete()
        await uow.expenses.save(expense)
        await uow.commit()

    block = only_block(await october_spending(make_uow))

    assert (block.total, block.expense_count) == (D("65.00"), 2)


async def test_spending_has_one_block_per_currency_ordered_by_code(make_uow):
    await bought(make_uow, at(2), (ProductCategory.DAIRY, "5.00"))
    await bought(make_uow, at(3), (ProductCategory.MEAT, "40.00"), currency="USD", store="us")
    await bought(make_uow, at(4), (ProductCategory.DAIRY, "6.00"))

    period = await october_spending(make_uow)

    assert [(b.currency, b.total, b.expense_count) for b in period.blocks] == [
        ("EUR", D("11.00"), 2),
        ("USD", D("40.00"), 1),
    ]
    assert [a.key for a in period.blocks[1].products] == ["meat"]
    assert (period.start, period.end) == (date(2026, 10, 1), date(2026, 11, 1))


async def test_spending_categories_are_expense_categories_over_all_expenses_largest_first(
    make_uow,
):
    groceries = await bought(make_uow, at(2), (ProductCategory.DAIRY, "5.00"))
    await bought(make_uow, at(3), (ProductCategory.DAIRY, "7.00"), store="other")
    await typed(make_uow, date(2026, 10, 1), "850.00", category=ExpenseCategory.RENT)
    await typed(make_uow, date(2026, 10, 5), "30.00", category=ExpenseCategory.RESTAURANTS)
    await typed(make_uow, date(2026, 10, 6), "20.00", category=ExpenseCategory.RESTAURANTS)
    async with make_uow() as uow:
        expense = await uow.expenses.find_by_receipt(groceries.id)
        expense.set_category(ExpenseCategory.HEALTH)
        await uow.expenses.save(expense)
        await uow.commit()

    block = only_block(await october_spending(make_uow))

    assert [(a.key, a.value) for a in block.categories] == [
        ("rent", D("850.00")),
        ("restaurants", D("50.00")),
        ("groceries", D("7.00")),
        ("health", D("5.00")),
    ]
    assert block.total == sum(a.value for a in block.categories)


async def test_spending_products_come_from_item_lines_of_receipt_expenses_largest_first(make_uow):
    await bought(make_uow, at(2), (ProductCategory.DAIRY, "5.00"), (ProductCategory.MEAT, "12.50"))
    await bought(
        make_uow,
        at(3),
        (ProductCategory.DAIRY, "4.00"),
        (ProductCategory.PANTRY, "0.00"),
        total="9.00",
    )
    await typed(make_uow, date(2026, 10, 4), "500.00")

    block = only_block(await october_spending(make_uow))

    assert [(a.key, a.value) for a in block.products] == [
        ("meat", D("12.50")),
        ("dairy", D("9.00")),
    ]
    assert block.total == D("526.50")


async def test_not_itemised_is_what_receipt_expenses_spent_beyond_their_item_lines(make_uow):
    await bought(make_uow, at(2), (ProductCategory.DAIRY, "5.00"), (ProductCategory.MEAT, "12.50"))
    await bought(make_uow, at(3), (ProductCategory.DAIRY, "4.00"), total="9.00")
    await typed(make_uow, date(2026, 10, 4), "500.00")

    block = only_block(await october_spending(make_uow))

    assert block.not_itemised == D("5.00")
    assert sum(a.value for a in block.products) + block.not_itemised == D("26.50")


async def test_a_receipt_without_a_total_adds_no_product_lines_so_not_itemised_stays_sound(
    make_uow,
):
    await bought(make_uow, at(2), (ProductCategory.DAIRY, "5.00"), total="5.00")
    unknown = await bought(make_uow, at(3), (ProductCategory.MEAT, "9.00"), store="other")
    async with make_uow() as uow:
        expense = await uow.expenses.find_by_receipt(unknown.id)
        expense.amount = D("0.00")
        await uow.expenses.save(expense)
        await uow.commit()

    block = only_block(await october_spending(make_uow))

    assert [(a.key, a.value) for a in block.products] == [("dairy", D("5.00"))]
    assert (block.total, block.expense_count, block.not_itemised) == (D("5.00"), 2, D("0.00"))


async def test_spending_products_follow_the_catalog_at_query_time(make_uow):
    await bought(make_uow, at(2), (ProductCategory.DAIRY, "5.00"))
    async with make_uow() as uow:
        catalog = await uow.catalog.get(1)
        [key] = catalog.products
        catalog.set_category(key, ProductCategory.PET)
        await uow.catalog.save(catalog)
        await uow.commit()

    block = only_block(await october_spending(make_uow))

    assert [a.key for a in block.products] == ["pet"]


async def test_spending_payees_are_summed_from_expense_amounts_largest_first(make_uow):
    await bought(make_uow, at(2), (ProductCategory.DAIRY, "5.00"), store="consum")
    await bought(make_uow, at(3), (ProductCategory.DAIRY, "4.00"), total="30.00", store="mercadona")
    await bought(make_uow, at(4), (ProductCategory.DAIRY, "4.00"), store="consum")
    await typed(make_uow, date(2026, 10, 5), "100.00", payee="landlord")
    await typed(make_uow, date(2026, 10, 6), "1.00")

    block = only_block(await october_spending(make_uow))

    assert [(a.label, a.value) for a in block.payees] == [
        ("Landlord", D("100.00")),
        ("Mercadona", D("30.00")),
        ("Consum", D("9.00")),
        ("", D("1.00")),
    ]
    assert block.payees[-1].key == "none"
    assert len({a.key for a in block.payees}) == 4


async def test_spending_sources_are_named_and_a_receipt_without_a_card_is_cash(make_uow):
    await bought(make_uow, at(2), (ProductCategory.DAIRY, "5.00"), card=("VISA", "0848"))
    await bought(make_uow, at(3), (ProductCategory.DAIRY, "6.00"), card=("VISA", "0848"))
    await bought(make_uow, at(4), (ProductCategory.DAIRY, "20.00"), card=(None, "1111"))
    await bought(make_uow, at(5), (ProductCategory.DAIRY, "1.00"))
    await typed(make_uow, date(2026, 10, 6), "2.00")

    block = only_block(await october_spending(make_uow))

    assert block.sources == [
        Amount(key="1111", label="•1111", value=D("20.00")),
        Amount(key="0848", label="VISA •0848", value=D("11.00")),
        Amount(key="none", label="", value=D("2.00")),
        Amount(key="cash", label="Cash", value=D("1.00")),
    ]


async def test_spending_ignores_another_users_expenses(make_uow):
    await bought(make_uow, at(2), (ProductCategory.DAIRY, "5.00"))
    await bought(make_uow, at(3), (ProductCategory.DAIRY, "99.00"), user_id=2)

    assert only_block(await october_spending(make_uow)).total == D("5.00")
    assert only_block(await october_spending(make_uow, user_id=2)).total == D("99.00")


async def test_an_empty_period_has_no_blocks(make_uow):
    await add_user(make_uow)

    period = await october_spending(make_uow)

    assert period == SpendingPeriod(start=date(2026, 10, 1), end=date(2026, 11, 1), blocks=[])


async def test_a_week_period_uses_the_same_bounds_rule(make_uow):
    await bought(make_uow, at(12, 7), (ProductCategory.DAIRY, "5.00"))  # Monday 09:00 Madrid
    await bought(make_uow, at(18, 21), (ProductCategory.DAIRY, "6.00"))  # Sunday 23:00 Madrid
    await bought(make_uow, at(18, 22), (ProductCategory.DAIRY, "7.00"))  # Monday 00:00 Madrid
    await bought(make_uow, at(11, 21), (ProductCategory.DAIRY, "8.00"))  # Saturday 23:00 Madrid

    async with make_uow() as uow:
        week = await uow.expenses.spending(1, date(2026, 10, 12), date(2026, 10, 19))

    assert only_block(week).total == D("11.00")


@pytest.mark.parametrize("size", [3, 30])
async def test_spending_runs_the_same_statements_whatever_the_size(make_uow, statements, size):
    for n in range(size):
        await bought(
            make_uow,
            at(1 + n % 28),
            (ProductCategory.DAIRY, "2.00"),
            (ProductCategory.MEAT, "3.00"),
            store=f"shop{n % 4}",
            card=("VISA", f"000{n % 3}") if n % 2 else None,
            currency="EUR" if n % 5 else "USD",
        )
    statements.clear()

    await october_spending(make_uow)

    assert len([s for s in statements if s.startswith("SELECT")]) == SPENDING_STATEMENTS


async def test_the_earliest_expense_day_ignores_deleted_expenses_and_other_users(make_uow):
    await add_user(make_uow)
    async with make_uow() as uow:
        assert await uow.expenses.earliest_spent_at(1) is None
    await bought(make_uow, at(10, month=3), deleted=True)
    await bought(make_uow, datetime(2026, 5, 31, 23, 30, tzinfo=UTC))
    await bought(make_uow, at(9))
    await bought(make_uow, at(1, month=1), user_id=2)

    async with make_uow() as uow:
        assert await uow.expenses.earliest_spent_at(1) == date(2026, 6, 1)
        assert await uow.expenses.earliest_spent_at(2) == date(2026, 1, 1)

    await typed(make_uow, date(2026, 2, 3))
    async with make_uow() as uow:
        assert await uow.expenses.earliest_spent_at(1) == date(2026, 2, 3)
