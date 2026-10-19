"""ExpenseService through the Unit of Work on real Postgres: the expense actions, history and
spending over expenses. Receipts come with their expenses (`tests.helpers.add_receipt`)."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from src.domain.enums import ExpenseCategory, ProductCategory
from src.domain.expense import Expense
from src.domain.receipt import Receipt
from src.exception import ExpenseNotFound, InvalidEdit, InvalidExpense, UserNotFound
from src.services.expense import ExpenseService
from src.services.results import PAGE_SIZE, Compared
from tests.domain.builders import parse, photo, product
from tests.helpers import MakeUow, add_allowed_user, add_receipt, seed_catalog


@pytest.fixture
async def service(make_uow: MakeUow) -> ExpenseService:
    await add_allowed_user(make_uow, 1)
    return ExpenseService(make_uow)


async def typed(make_uow: MakeUow, day: date, amount: str = "20.00", *, user_id: int = 1) -> int:
    """An expense typed by hand (no receipt behind it); returns its id."""
    async with make_uow() as uow:
        expense = await uow.expenses.add(
            Expense.start_manual(user_id, amount=Decimal(amount), currency="EUR", spent_at=day)
        )
        await uow.commit()
    assert expense.id is not None
    return expense.id


# --- one expense -----------------------------------------------------------------------------


async def expense_of(make_uow: MakeUow, receipt_id: int) -> Expense:
    async with make_uow() as uow:
        expense = await uow.expenses.find_by_receipt(receipt_id)
    assert expense is not None
    return expense


async def test_the_card_of_a_receipt_expense_names_its_payee_and_card(service, make_uow):
    bought = parse(
        product("mercadona::leche"),
        card_brand="VISA",
        card_last4="0848",
        total=Decimal("47.50"),
    )
    await seed_catalog(make_uow, bought)
    receipt = Receipt.start(1, photo())
    receipt.apply_parse(bought)
    receipt = await add_receipt(make_uow, receipt)
    expense = await expense_of(make_uow, receipt.id)

    card = await service.card(1, expense.id)

    assert (
        card.expense_id,
        card.amount,
        card.currency,
        card.spent_at,
        card.payee_name,
        card.payment_source_name,
        card.category,
        card.tags,
        card.receipt_id,
        card.deleted,
    ) == (
        expense.id,
        Decimal("47.50"),
        "EUR",
        date(2026, 10, 14),
        "Mercadona",
        "VISA •0848",
        "groceries",
        [],
        receipt.id,
        False,
    )
    assert await service.for_receipt(1, receipt.id) == card


async def test_the_card_of_a_typed_expense_has_no_receipt(service, make_uow):
    expense_id = await typed(make_uow, date(2026, 10, 1), "850.00")

    card = await service.card(1, expense_id)

    assert (card.receipt_id, card.payee_name, card.payment_source_name) == (None, None, None)
    assert (card.amount, card.category) == (Decimal("850.00"), "other")
    with pytest.raises(ExpenseNotFound):
        await service.for_receipt(1, 999)


async def test_set_category_persists_and_returns_the_card(service, make_uow):
    expense_id = await typed(make_uow, date(2026, 10, 1))

    card = await service.set_category(1, expense_id, "health")

    assert card.category == "health"
    async with make_uow() as uow:
        assert (await uow.expenses.get(expense_id)).category is ExpenseCategory.HEALTH


async def test_set_category_refuses_an_unknown_category_and_changes_nothing(service, make_uow):
    expense_id = await typed(make_uow, date(2026, 10, 1))

    with pytest.raises(InvalidEdit):
        await service.set_category(1, expense_id, "fruit_and_vegetables")  # a product category

    assert (await service.card(1, expense_id)).category == "other"


async def test_set_tags_persists_them_normalised(service, make_uow):
    expense_id = await typed(make_uow, date(2026, 10, 1))

    card = await service.set_tags(1, expense_id, [" Home ", "monthly", "home"])

    assert card.tags == ["home", "monthly"]
    async with make_uow() as uow:
        assert (await uow.expenses.get(expense_id)).tags == ["home", "monthly"]
    assert (await service.set_tags(1, expense_id, [])).tags == []


async def test_too_many_tags_are_refused_and_change_nothing(service, make_uow):
    expense_id = await typed(make_uow, date(2026, 10, 1))
    await service.set_tags(1, expense_id, ["a"])

    with pytest.raises(InvalidExpense):
        await service.set_tags(1, expense_id, [f"t{n}" for n in range(11)])

    assert (await service.card(1, expense_id)).tags == ["a"]


async def test_a_deleted_expense_still_answers_but_refuses_changes(service, make_uow):
    expense_id = await typed(make_uow, date(2026, 10, 1))
    async with make_uow() as uow:
        expense = await uow.expenses.get(expense_id)
        expense.soft_delete()
        await uow.expenses.save(expense)
        await uow.commit()

    assert (await service.card(1, expense_id)).deleted is True
    with pytest.raises(InvalidExpense):
        await service.set_category(1, expense_id, "rent")


async def test_another_users_expense_is_not_found(service, make_uow):
    await add_allowed_user(make_uow, 2)
    theirs = await typed(make_uow, date(2026, 10, 1), user_id=2)
    bought = parse(product("mercadona::leche"))
    await seed_catalog(make_uow, bought, user_id=2)
    receipt = Receipt.start(2, photo("theirs"))
    receipt.apply_parse(bought)
    receipt = await add_receipt(make_uow, receipt, user_id=2)

    with pytest.raises(ExpenseNotFound):
        await service.card(1, theirs)
    with pytest.raises(ExpenseNotFound):
        await service.set_category(1, theirs, "rent")
    with pytest.raises(ExpenseNotFound):
        await service.set_tags(1, theirs, ["x"])
    with pytest.raises(ExpenseNotFound):
        await service.for_receipt(1, receipt.id)
    assert (await service.card(2, theirs)).category == "other"


async def test_a_missing_expense_is_not_found(service):
    with pytest.raises(ExpenseNotFound):
        await service.card(1, 987654)


# --- history ---------------------------------------------------------------------------------


async def bought_on(make_uow: MakeUow, n: int, purchased_at: datetime, *, user_id: int = 1):
    """A parsed receipt of the user, bought at this moment (each one has its own key)."""
    bought = parse(
        product(f"mercadona::item{n}"),
        purchased_at=purchased_at,
        receipt_number=str(n),
        receipt_key=f"mercadona|{n}",
    )
    await seed_catalog(make_uow, bought, user_id=user_id)
    receipt = Receipt.start(user_id, photo(f"history{user_id}-{n}"))
    receipt.apply_parse(bought)
    return await add_receipt(make_uow, receipt)


async def test_history_shows_the_day_in_the_users_time_zone_at_the_time_of_writing(
    service, make_uow, connection
):
    await bought_on(make_uow, 1, datetime(2026, 10, 31, 23, 30, tzinfo=UTC))
    await connection.execute(text("update users set timezone = 'UTC' where id = 1"))
    await bought_on(make_uow, 2, datetime(2026, 10, 31, 23, 30, tzinfo=UTC))

    november = await service.history(1, 2026, 11)
    october = await service.history(1, 2026, 10)

    # The first receipt was written for a Madrid user, the second for a UTC one.
    assert [r.day for r in november.rows] == [date(2026, 11, 1)]
    assert [r.day for r in october.rows] == [date(2026, 10, 31)]


async def test_history_lists_a_failed_receipt_by_the_users_local_day_without_counting_it(
    service, make_uow
):
    failed = Receipt.start(
        1, replace(photo("failed-late"), received_at=datetime(2026, 10, 31, 23, 30, tzinfo=UTC))
    )
    failed.mark_parsing()
    failed.mark_failed("timeout")
    failed = await add_receipt(make_uow, failed)

    november = await service.history(1, 2026, 11)
    october = await service.history(1, 2026, 10)

    assert [(r.receipt_id, r.expense_id, r.status) for r in november.rows] == [
        (failed.id, None, "failed")
    ]
    assert (november.total_rows, november.expense_count, november.totals) == (1, 0, [])
    assert october.rows == []


async def test_history_of_an_unknown_user_is_refused(service):
    with pytest.raises(UserNotFound):
        await service.history(404, 2026, 10)


async def test_history_pages_by_eight_and_a_page_past_the_end_is_the_last_page(service, make_uow):
    for n in range(1, 11):
        await bought_on(make_uow, n, datetime(2026, 10, n, 12, tzinfo=UTC))

    first = await service.history(1, 2026, 10)
    second = await service.history(1, 2026, 10, page=1)
    past = await service.history(1, 2026, 10, page=9)
    before = await service.history(1, 2026, 10, page=-3)

    assert PAGE_SIZE == 8
    assert (len(first.rows), first.total_rows) == (8, 10)
    assert [r.day.day for r in second.rows] == [2, 1]
    assert past == second
    assert before == first


async def test_history_past_the_end_of_an_empty_month_is_an_empty_page(service):
    page = await service.history(1, 2026, 10, page=3)

    assert (page.rows, page.total_rows) == ([], 0)


async def test_another_users_payee_id_yields_an_empty_page(service, make_uow):
    await add_allowed_user(make_uow, 2)
    await bought_on(make_uow, 1, datetime(2026, 10, 10, 12, tzinfo=UTC))
    await bought_on(make_uow, 2, datetime(2026, 10, 10, 12, tzinfo=UTC), user_id=2)
    async with make_uow() as uow:
        theirs = (await uow.catalog.get(2)).payees["mercadona"].id

    page = await service.history(1, 2026, 10, payee_id=theirs)

    assert (page.rows, page.total_rows, page.totals) == ([], 0, [])
    assert page.payee_name is None
    assert len(page.payees) == 1


async def test_there_is_no_later_month_for_the_current_month_or_beyond(service, make_uow):
    now = datetime.now(ZoneInfo("Europe/Madrid"))  # the user's default time zone
    next_month = datetime(now.year + (now.month == 12), now.month % 12 + 1, 15, 12, tzinfo=UTC)
    await bought_on(make_uow, 1, now)
    await bought_on(make_uow, 2, next_month)

    current = await service.history(1, now.year, now.month)
    last_year = await service.history(1, now.year - 1, now.month)
    ahead = await service.history(1, next_month.year, next_month.month)

    assert current.has_later is False
    assert (current.has_earlier, last_year.has_later) == (False, True)
    assert ahead.has_later is False


# --- spending --------------------------------------------------------------------------------

D = Decimal
_spent_ids = iter(range(1, 10_000))


async def spent(
    make_uow: MakeUow,
    purchased_at: datetime,
    amount: str,
    *,
    category: ProductCategory = ProductCategory.DAIRY,
    store: str = "mercadona",
    currency: str = "EUR",
    card: str | None = None,
    total: str | None = None,
    user_id: int = 1,
) -> Receipt:
    """A parsed receipt with one item line of `amount`; the receipt total is `total` if given."""
    n = next(_spent_ids)
    bought = parse(
        product(f"{store}::item{n}", total=amount, category=category),
        store_key=store,
        store_name=store.capitalize(),
        purchased_at=purchased_at,
        receipt_number=str(n),
        receipt_key=f"{store}|{n}",
        total=D(total or amount),
        currency=currency,
        card_brand="VISA" if card else None,
        card_last4=card,
    )
    await seed_catalog(make_uow, bought, user_id=user_id)
    receipt = Receipt.start(user_id, photo(f"spent{user_id}-{n}"))
    receipt.apply_parse(bought)
    return await add_receipt(make_uow, receipt)


def october(day: int = 10, hour: int = 12) -> datetime:
    return datetime(2026, 10, day, hour, tzinfo=UTC)


def september(day: int = 10) -> datetime:
    return datetime(2026, 9, day, 12, tzinfo=UTC)


def line(lines: list[Compared], key: str) -> Compared:
    [found] = [x for x in lines if x.key == key]
    return found


async def test_spending_of_a_month_compares_with_the_previous_month(service, make_uow):
    await spent(
        make_uow, october(), "120.00", category=ProductCategory.MEAT, store="a", card="0848"
    )
    await spent(make_uow, october(11), "30.00", category=ProductCategory.DAIRY, store="b")
    await spent(
        make_uow, september(), "100.00", category=ProductCategory.MEAT, store="a", card="0848"
    )
    await spent(make_uow, september(11), "60.00", category=ProductCategory.DAIRY, store="b")
    await spent(make_uow, september(12), "10.00", category=ProductCategory.PET, store="c")

    report = await service.spending(1, "month", date(2026, 10, 14))

    assert (report.kind, report.start, report.end) == (
        "month",
        date(2026, 10, 1),
        date(2026, 11, 1),
    )
    [block] = report.blocks
    assert (block.currency, block.total, block.expense_count) == ("EUR", D("150.00"), 2)
    assert block.previous_total == D("170.00")
    assert block.change == -12
    meat, dairy = block.products
    assert (meat.key, meat.value, meat.share, meat.previous, meat.change) == (
        "meat",
        D("120.00"),
        80,
        D("100.00"),
        20,
    )
    assert (dairy.key, dairy.share, dairy.previous, dairy.change) == ("dairy", 20, D("60.00"), -50)
    assert [(x.label, x.change) for x in block.payees] == [("A", 20), ("B", -50)]
    assert [(x.label, x.share) for x in block.sources] == [("VISA •0848", 80), ("Cash", 20)]
    assert [x.key for x in block.sources] == ["0848", "cash"]


async def test_a_line_without_a_previous_value_is_new_and_a_zero_previous_has_no_change(
    service, make_uow
):
    await spent(make_uow, october(), "50.00", category=ProductCategory.MEAT, store="a")
    await spent(make_uow, october(11), "20.00", category=ProductCategory.PET, store="b")
    await spent(make_uow, september(), "10.00", category=ProductCategory.MEAT, store="a")
    await spent(make_uow, september(11), "0.00", category=ProductCategory.PET, store="b")

    [block] = (await service.spending(1, "month", date(2026, 10, 14))).blocks

    pet = line(block.products, "pet")
    assert (pet.previous, pet.change) == (None, None)  # not in the previous period's lines
    shop_b = block.payees[1]
    assert (shop_b.label, shop_b.previous, shop_b.change) == ("B", D("0.00"), None)
    assert line(block.products, "meat").change == 400


async def test_a_currency_new_this_period_has_no_previous_total(service, make_uow):
    await spent(make_uow, october(), "50.00")
    await spent(make_uow, september(), "10.00", currency="USD")

    [block] = (await service.spending(1, "month", date(2026, 10, 14))).blocks

    assert (block.previous_total, block.change) == (None, None)
    assert {x.previous for x in block.products} == {None}


async def test_shares_sum_to_about_a_hundred_with_not_itemised_included(service, make_uow):
    await spent(make_uow, october(), "10.00", category=ProductCategory.MEAT)
    await spent(make_uow, october(), "10.00", category=ProductCategory.DAIRY)
    await spent(make_uow, october(), "10.00", category=ProductCategory.PET, total="13.00")

    [block] = (await service.spending(1, "month", date(2026, 10, 14))).blocks

    assert block.total == D("33.00")
    assert [x.share for x in block.products if x.key != "not_itemised"] == [30, 30, 30]
    extra = line(block.products, "not_itemised")
    assert (extra.value, extra.share, extra.label) == (D("3.00"), 9, "")
    assert block.products[-1] is extra
    assert abs(sum(x.share for x in block.products) - 100) <= 2


async def test_a_negligible_not_itemised_remainder_is_left_out(service, make_uow):
    await spent(make_uow, october(), "10.00")

    [block] = (await service.spending(1, "month", date(2026, 10, 14))).blocks

    assert [x.key for x in block.products] == ["dairy"]


async def test_only_the_five_largest_stores_are_kept(service, make_uow):
    for n in range(7):
        await spent(make_uow, october(), f"{10 + n}.00", store=f"shop{n}")

    [block] = (await service.spending(1, "month", date(2026, 10, 14))).blocks

    assert [x.label for x in block.payees] == ["Shop6", "Shop5", "Shop4", "Shop3", "Shop2"]
    assert block.expense_count == 7


async def test_the_users_currency_comes_first_then_alphabetical(service, make_uow, connection):
    await spent(make_uow, october(), "5.00", currency="EUR")
    await spent(make_uow, october(), "5.00", currency="USD", store="us")
    await spent(make_uow, october(), "5.00", currency="GBP", store="uk")

    eur_first = await service.spending(1, "month", date(2026, 10, 14))
    await connection.execute(text("update users set default_currency = 'USD' where id = 1"))
    usd_first = await service.spending(1, "month", date(2026, 10, 14))

    assert [b.currency for b in eur_first.blocks] == ["EUR", "GBP", "USD"]
    assert [b.currency for b in usd_first.blocks] == ["USD", "EUR", "GBP"]


async def test_has_earlier_looks_for_an_expense_before_the_period(service, make_uow):
    await spent(make_uow, october(), "5.00")

    assert (await service.spending(1, "month", date(2026, 10, 14))).has_earlier is False
    await spent(make_uow, datetime(2026, 9, 30, 22, tzinfo=UTC), "5.00")  # 1 Oct 00:00 in Madrid
    assert (await service.spending(1, "month", date(2026, 10, 14))).has_earlier is False
    await spent(make_uow, datetime(2026, 9, 30, 21, tzinfo=UTC), "5.00")  # 30 Sep 23:00
    assert (await service.spending(1, "month", date(2026, 10, 14))).has_earlier is True
    assert (await service.spending(1, "week", date(2026, 10, 14))).has_earlier is True


async def test_an_empty_period_has_no_blocks_but_may_have_an_earlier_one(service, make_uow):
    await spent(make_uow, september(), "5.00")

    report = await service.spending(1, "month", date(2026, 10, 14))

    assert report.blocks == []
    assert report.has_earlier is True


async def test_a_week_is_compared_with_the_week_before(service, make_uow):
    await spent(make_uow, october(13), "30.00")
    await spent(make_uow, october(6), "20.00")
    await spent(make_uow, october(5, 6), "20.00")  # Monday 08:00 Madrid, the previous week
    await spent(make_uow, october(4, 12), "99.00")  # the Sunday before that

    report = await service.spending(1, "week", date(2026, 10, 14))

    assert (report.start, report.end) == (date(2026, 10, 12), date(2026, 10, 19))
    [block] = report.blocks
    assert (block.total, block.previous_total, block.change) == (D("30.00"), D("40.00"), -25)


async def test_is_current_for_the_period_that_holds_today(service):
    today = datetime.now(ZoneInfo("Europe/Madrid")).date()

    here = await service.spending(1, "month", today)
    later = await service.spending(1, "month", today + timedelta(days=62))
    earlier = await service.spending(1, "week", today - timedelta(days=7))

    assert (here.is_current, later.is_current, earlier.is_current) == (True, False, False)


async def test_spending_buckets_by_the_day_the_expense_was_written_with(
    service, make_uow, connection
):
    await spent(make_uow, datetime(2026, 10, 31, 23, 30, tzinfo=UTC), "5.00")  # Madrid: 1 Nov
    await connection.execute(text("update users set timezone = 'UTC' where id = 1"))
    await spent(make_uow, datetime(2026, 10, 31, 23, 30, tzinfo=UTC), "7.00")  # UTC: 31 Oct

    [block] = (await service.spending(1, "month", date(2026, 10, 14))).blocks

    assert block.total == D("7.00")


async def test_spending_of_an_unknown_user_is_refused(service):
    with pytest.raises(UserNotFound):
        await service.spending(404, "month", date(2026, 10, 14))


async def test_spending_never_shows_another_users_receipts(service, make_uow):
    await add_allowed_user(make_uow, 2)
    await spent(make_uow, october(), "77.00", user_id=2)

    assert (await service.spending(1, "month", date(2026, 10, 14))).blocks == []


async def test_spending_has_expense_categories_and_the_product_breakdown_of_groceries(
    service, make_uow
):
    await spent(make_uow, october(), "40.00", category=ProductCategory.MEAT)
    await spent(make_uow, september(), "10.00", category=ProductCategory.MEAT)
    rent = await typed(make_uow, date(2026, 10, 1), "850.00")
    await service.set_category(1, rent, "rent")

    [block] = (await service.spending(1, "month", date(2026, 10, 14))).blocks

    assert [(x.key, x.value, x.share) for x in block.categories] == [
        ("rent", D("850.00"), 96),
        ("groceries", D("40.00"), 4),
    ]
    assert line(block.categories, "groceries").previous == D("10.00")
    assert [(x.key, x.value) for x in block.products] == [("meat", D("40.00"))]
    assert block.expense_count == 2
