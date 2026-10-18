"""The `Expense` aggregate as plain Python: no database."""

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from src.domain.enums import ExpenseCategory
from src.domain.expense import MAX_TAG_LENGTH, MAX_TAGS, Expense
from src.domain.receipt import Header
from src.exception import ExpenseFollowsReceipt, InvalidExpense
from tests.domain.builders import WHEN

MADRID = ZoneInfo("Europe/Madrid")
D = Decimal


def manual(**fields) -> Expense:
    args = {
        "amount": D("12.50"),
        "currency": "EUR",
        "spent_at": date(2026, 10, 14),
        "category": ExpenseCategory.RESTAURANTS,
    } | fields
    return Expense.start_manual(1, **args)


def header(**fields) -> Header:
    base = Header(
        store_key="mercadona",
        purchased_at=datetime(2026, 10, 14, 17, 5, tzinfo=UTC),
        currency="EUR",
        total=D("47.50"),
    )
    return replace(base, **fields)


def from_receipt(head: Header | None = None, **fields) -> Expense:
    args = {
        "payee_key": "mercadona",
        "payment_source_id": 3,
        "received_at": WHEN,
        "tz": MADRID,
        "default_currency": "EUR",
    } | fields
    return Expense.from_receipt(1, 9, head or header(), **args)


def sync(expense: Expense, head: Header, **fields) -> None:
    args = {
        "payee_key": "mercadona",
        "payment_source_id": 3,
        "received_at": WHEN,
        "tz": MADRID,
        "default_currency": "EUR",
    } | fields
    expense.sync_with_receipt(head, **args)


# --- a manual expense -------------------------------------------------------------------


def test_a_manual_expense_keeps_what_was_typed():
    expense = manual(payee_key="landlord", payment_source_id=2, tags=["Home"])

    assert (expense.amount, expense.currency, expense.spent_at) == (
        D("12.50"),
        "EUR",
        date(2026, 10, 14),
    )
    assert (expense.payee_key, expense.payment_source_id) == ("landlord", 2)
    assert (expense.category, expense.tags, expense.receipt_id) == (
        ExpenseCategory.RESTAURANTS,
        ["home"],
        None,
    )
    assert (expense.id, expense.deleted_at) == (None, None)


@pytest.mark.parametrize("amount", ["0", "0.00", "-1", "-0.01", "0.004"])
def test_a_manual_expense_needs_a_positive_amount(amount):
    with pytest.raises(InvalidExpense):
        manual(amount=D(amount))


def test_the_amount_is_rounded_to_cents():
    assert manual(amount=D("3.456")).amount == D("3.46")


@pytest.mark.parametrize("currency", ["", "EU", "EURO", "E1R", "12 "])
def test_a_currency_is_three_letters(currency):
    with pytest.raises(InvalidExpense):
        manual(currency=currency)


def test_the_currency_is_upper_cased():
    assert manual(currency=" usd ").currency == "USD"


def test_a_stored_expense_cannot_be_negative():
    with pytest.raises(InvalidExpense):
        Expense(user_id=1, amount=D("-1"), currency="EUR", spent_at=date(2026, 10, 14))


# --- from a receipt ---------------------------------------------------------------------


def test_from_receipt_copies_the_header_facts_and_starts_as_groceries():
    expense = from_receipt()

    assert (expense.amount, expense.currency, expense.spent_at) == (
        D("47.50"),
        "EUR",
        date(2026, 10, 14),
    )
    assert (expense.payee_key, expense.payment_source_id, expense.receipt_id) == (
        "mercadona",
        3,
        9,
    )
    assert (expense.category, expense.tags) == (ExpenseCategory.GROCERIES, [])


def test_the_day_is_the_users_local_day():
    late = datetime(2026, 10, 14, 23, 30, tzinfo=UTC)  # 01:30 on the 15th in Madrid (CEST)

    assert from_receipt(header(purchased_at=late)).spent_at == date(2026, 10, 15)
    assert from_receipt(header(purchased_at=late), tz=ZoneInfo("UTC")).spent_at == date(
        2026, 10, 14
    )


def test_without_a_purchase_time_the_day_is_the_photos():
    received = datetime(2026, 10, 20, 22, 30, tzinfo=UTC)

    expense = from_receipt(header(purchased_at=None), received_at=received)

    assert expense.spent_at == date(2026, 10, 21)  # 00:30 in Madrid


def test_without_a_currency_the_default_is_used():
    assert from_receipt(header(currency=None), default_currency="USD").currency == "USD"


@pytest.mark.parametrize("total", [None, D("0"), D("-5.00")])
def test_an_unreadable_total_is_a_zero_amount(total):
    assert from_receipt(header(total=total)).amount == D("0.00")


def test_a_receipt_expense_may_have_no_payee_or_source():
    expense = from_receipt(payee_key=None, payment_source_id=None)

    assert (expense.payee_key, expense.payment_source_id) == (None, None)


# --- sync_with_receipt ------------------------------------------------------------------


def test_sync_copies_only_the_header_facts():
    expense = from_receipt()
    expense.set_category(ExpenseCategory.HEALTH)
    expense.set_tags(["pharmacy"])
    new_header = header(
        total=D("12.00"),
        currency="USD",
        purchased_at=datetime(2026, 10, 1, 10, 0, tzinfo=UTC),
    )

    sync(expense, new_header, payee_key="cvs", payment_source_id=8)

    assert (expense.amount, expense.currency, expense.spent_at) == (
        D("12.00"),
        "USD",
        date(2026, 10, 1),
    )
    assert (expense.payee_key, expense.payment_source_id) == ("cvs", 8)
    assert (expense.category, expense.tags, expense.receipt_id) == (
        ExpenseCategory.HEALTH,
        ["pharmacy"],
        9,
    )


def test_sync_does_not_mark_the_tags_changed():
    expense = from_receipt()

    sync(expense, header(total=D("1.00")))

    assert expense.tags_changed is False


def test_sync_needs_a_receipt():
    with pytest.raises(InvalidExpense):
        sync(manual(), header())


def test_sync_of_a_deleted_expense_is_refused():
    expense = from_receipt()
    expense.soft_delete()

    with pytest.raises(InvalidExpense):
        sync(expense, header())


# --- direct edits -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "edit",
    [
        lambda e: e.set_amount(D("1.00")),
        lambda e: e.set_payee("other"),
        lambda e: e.set_source(None),
        lambda e: e.set_date(date(2026, 1, 1)),
    ],
    ids=["amount", "payee", "source", "date"],
)
def test_a_receipt_expense_refuses_direct_edits_of_receipt_facts(edit):
    expense = from_receipt()
    before = replace(expense)

    with pytest.raises(ExpenseFollowsReceipt):
        edit(expense)

    assert expense == before


def test_a_manual_expense_accepts_every_edit():
    expense = manual()

    expense.set_amount(D("20"))
    expense.set_payee("bar")
    expense.set_source(4)
    expense.set_date(date(2026, 10, 1))
    expense.set_category(ExpenseCategory.GIFTS)

    assert (expense.amount, expense.payee_key, expense.payment_source_id) == (D("20.00"), "bar", 4)
    assert (expense.spent_at, expense.category) == (date(2026, 10, 1), ExpenseCategory.GIFTS)


def test_set_payee_and_source_accept_none():
    expense = manual(payee_key="bar", payment_source_id=4)

    expense.set_payee(None)
    expense.set_source(None)

    assert (expense.payee_key, expense.payment_source_id) == (None, None)


@pytest.mark.parametrize("amount", ["0", "-3", "0.004"])
def test_set_amount_needs_a_positive_amount(amount):
    expense = manual()

    with pytest.raises(InvalidExpense):
        expense.set_amount(D(amount))

    assert expense.amount == D("12.50")


def test_the_category_of_a_receipt_expense_can_be_changed():
    expense = from_receipt()

    expense.set_category(ExpenseCategory.HEALTH)

    assert expense.category is ExpenseCategory.HEALTH


def test_an_unknown_category_is_refused():
    with pytest.raises(ValueError):
        manual().set_category("nonsense")  # type: ignore[arg-type]


# --- tags -------------------------------------------------------------------------------


def test_tags_are_stripped_lower_cased_unique_and_sorted():
    expense = manual()

    expense.set_tags([" Holiday ", "kids", "HOLIDAY", "", "  ", "Åre"])

    assert expense.tags == ["holiday", "kids", "åre"]
    assert expense.tags_changed is True


def test_a_tag_longer_than_the_cap_is_refused():
    expense = manual(tags=["keep"])

    with pytest.raises(InvalidExpense):
        expense.set_tags(["x" * (MAX_TAG_LENGTH + 1)])

    assert expense.tags == ["keep"]
    assert expense.tags_changed is False


def test_a_tag_of_the_cap_length_is_fine():
    assert manual(tags=["x" * MAX_TAG_LENGTH]).tags == ["x" * MAX_TAG_LENGTH]


def test_more_tags_than_the_cap_are_refused():
    many = [f"t{n}" for n in range(MAX_TAGS + 1)]
    expense = manual()

    with pytest.raises(InvalidExpense):
        expense.set_tags(many)
    assert manual(tags=many[:MAX_TAGS]).tags == sorted(many[:MAX_TAGS])


def test_repeats_do_not_count_towards_the_cap():
    tags = [f"t{n}" for n in range(MAX_TAGS)]

    assert len(manual(tags=tags + [t.upper() for t in tags]).tags) == MAX_TAGS


def test_mark_saved_resets_the_tag_flag():
    expense = manual()
    expense.set_tags(["a"])

    expense.mark_saved()

    assert expense.tags_changed is False


# --- soft_delete ------------------------------------------------------------------------


def test_soft_delete_stamps_the_time_and_closes_the_expense():
    expense = manual()
    when = datetime(2026, 10, 15, tzinfo=UTC)

    expense.soft_delete(when)

    assert expense.deleted_at == when
    with pytest.raises(InvalidExpense):
        expense.set_category(ExpenseCategory.GIFTS)
    with pytest.raises(InvalidExpense):
        expense.set_tags(["a"])
    with pytest.raises(InvalidExpense):
        expense.set_amount(D("1"))


def test_soft_delete_twice_is_refused_and_keeps_the_first_time():
    expense = manual()
    first = datetime(2026, 10, 15, tzinfo=UTC)
    expense.soft_delete(first)

    with pytest.raises(InvalidExpense):
        expense.soft_delete(datetime(2026, 10, 16, tzinfo=UTC))

    assert expense.deleted_at == first


def test_a_receipt_expense_can_be_deleted():
    expense = from_receipt()

    expense.soft_delete()

    assert expense.deleted_at is not None


# --- restore ----------------------------------------------------------------------------


def test_restore_reopens_a_deleted_expense_and_keeps_what_the_user_set():
    expense = from_receipt()
    expense.set_category(ExpenseCategory.HEALTH)
    expense.soft_delete()

    expense.restore()

    assert expense.deleted_at is None
    assert expense.category is ExpenseCategory.HEALTH
    expense.set_category(ExpenseCategory.GIFTS)


def test_restoring_an_open_expense_is_refused():
    with pytest.raises(InvalidExpense):
        manual().restore()


# --- deleting by hand -----------------------------------------------------------------------


def test_a_manual_expense_is_deleted_by_hand():
    expense = manual()

    expense.delete_by_hand(datetime(2026, 10, 15, tzinfo=UTC))

    assert expense.deleted_at == datetime(2026, 10, 15, tzinfo=UTC)


def test_a_receipt_expense_is_not_deleted_by_hand_but_with_its_receipt():
    expense = from_receipt()

    with pytest.raises(ExpenseFollowsReceipt):
        expense.delete_by_hand()

    assert expense.deleted_at is None


def test_an_expense_deleted_by_hand_cannot_be_deleted_again():
    expense = manual()
    expense.delete_by_hand()

    with pytest.raises(InvalidExpense):
        expense.delete_by_hand()
