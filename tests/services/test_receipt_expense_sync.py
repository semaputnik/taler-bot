"""A receipt and its expense stay in step (ADR-0003): created on the first parse, synced on every
header change, deleted with the receipt or when it stops being a purchase. All in the receipt's
own Unit of Work."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text

from src.database.repositories.expense import SqlAlchemyExpenseRepository
from src.database.repositories.receipt import SqlAlchemyReceiptRepository
from src.domain.enums import ExpenseCategory, PaymentSourceKind, ReceiptStatus
from src.domain.expense import Expense
from src.exception import DatabaseException, DataViolationError
from src.integration.llm import LLMError
from src.services.expense import ExpenseService
from src.services.receipt import ReceiptService
from tests.domain.builders import parse
from tests.helpers import MakeUow, add_allowed_user
from tests.services.test_receipt_parse import PAID_WITH_CARD, UNSEEN_CARD, intake
from tests.services.test_receipt_service import MILK, mixed_receipt, parsed_receipt
from tests.stubs import StubReceiptParser, fixture, output_of

D = Decimal
VISA = "VISA •0848"


@pytest.fixture
def parser() -> StubReceiptParser:
    return StubReceiptParser()


@pytest.fixture
async def service(make_uow: MakeUow, tmp_storage, parser) -> ReceiptService:
    await add_allowed_user(make_uow, 1)
    await add_allowed_user(make_uow, 2, first_name="Bo", username="bo")
    return ReceiptService(make_uow, tmp_storage, parser)


@pytest.fixture
def expenses(make_uow: MakeUow) -> ExpenseService:
    return ExpenseService(make_uow)


async def expense_of(make_uow: MakeUow, receipt_id: int) -> Expense | None:
    async with make_uow() as uow:
        return await uow.expenses.find_by_receipt(receipt_id)


async def sources(make_uow: MakeUow, user_id: int = 1) -> dict[str, str]:
    async with make_uow() as uow:
        catalog = await uow.catalog.get(user_id)
    return {s.last4 or "cash": s.name for s in catalog.payment_sources.values()}


# --- the first parse -------------------------------------------------------------------------


async def test_a_first_parse_creates_the_expense_from_the_header(
    service, parser, make_uow, expenses
):
    receipt_id = await intake(service, parser, PAID_WITH_CARD, unique="a1")

    result = await service.parse(1, receipt_id)

    expense = await expense_of(make_uow, receipt_id)
    assert expense is not None
    assert (expense.amount, expense.currency, expense.spent_at) == (
        D("7.58"),
        "EUR",
        date(2026, 10, 10),
    )
    assert (expense.payee_key, expense.category, expense.tags) == (
        "consum",
        ExpenseCategory.GROCERIES,
        [],
    )
    assert expense.deleted_at is None
    card = await expenses.for_receipt(1, receipt_id)
    assert (card.payee_name, card.payment_source_name, card.receipt_id) == (
        "Consum",
        VISA,
        receipt_id,
    )
    assert (
        result.card.expense_id,
        result.card.expense_category,
        result.card.payment_source_name,
    ) == (expense.id, "groceries", VISA)
    assert await sources(make_uow) == {"0848": VISA}


async def test_a_receipt_paid_without_a_card_is_paid_in_cash(service, parser, make_uow):
    raw = fixture(PAID_WITH_CARD)["raw"]
    raw["payment"] = {**raw["payment"], "method": "cash", "card_brand": None, "card_last4": None}
    receipt_id = await intake(service, parser, PAID_WITH_CARD, unique="c1")
    parser.outputs[b"c1"] = output_of(raw)

    result = await service.parse(1, receipt_id)

    assert result.card.payment_source_name == "Cash"
    assert await sources(make_uow) == {"cash": "Cash"}
    async with make_uow() as uow:
        catalog = await uow.catalog.get(1)
    [source] = catalog.payment_sources.values()
    assert source.kind is PaymentSourceKind.CASH
    expense = await expense_of(make_uow, receipt_id)
    assert expense.payment_source_id == source.id


async def test_receipts_with_one_card_share_its_source_and_each_user_has_their_own(
    service, parser, make_uow
):
    first = await intake(service, parser, PAID_WITH_CARD, unique="s1")
    second = await intake(service, parser, UNSEEN_CARD, unique="s2")
    theirs = await intake(service, parser, PAID_WITH_CARD, unique="s3", user_id=2)
    raw = fixture(UNSEEN_CARD)["raw"]
    raw["payment"] = {**raw["payment"], "card_brand": "VISA", "card_last4": "0848"}
    parser.outputs[b"s2"] = output_of(raw)

    await service.parse(1, first)
    await service.parse(1, second)
    await service.parse(2, theirs)

    one, two = await expense_of(make_uow, first), await expense_of(make_uow, second)
    assert one.payment_source_id == two.payment_source_id
    assert await sources(make_uow) == {"0848": VISA}
    assert (await expense_of(make_uow, theirs)).payment_source_id != one.payment_source_id


async def test_the_day_is_the_users_local_day_of_the_purchase(
    service, parser, make_uow, connection
):
    await connection.execute(text("update users set timezone = 'Pacific/Auckland' where id = 1"))
    raw = fixture(PAID_WITH_CARD)["raw"]
    raw["receipt"] = {**raw["receipt"], "purchased_at": "2026-10-10T20:06:00"}
    receipt_id = await intake(service, parser, PAID_WITH_CARD, unique="t1")
    parser.outputs[b"t1"] = output_of(raw)

    await service.parse(1, receipt_id)

    # 20:06 on 10 October in Auckland (the purchase time is read in the user's zone).
    assert (await expense_of(make_uow, receipt_id)).spent_at == date(2026, 10, 10)


async def test_clearing_the_total_gives_an_expense_of_zero(service, parser, make_uow):
    receipt_id = await intake(service, parser, PAID_WITH_CARD, unique="z1")
    await service.parse(1, receipt_id)

    await service.edit_header(1, receipt_id, "total", None)

    assert (await expense_of(make_uow, receipt_id)).amount == D("0.00")


async def test_a_receipt_that_is_not_a_receipt_has_no_expense(service, parser, make_uow):
    receipt_id = await intake(service, parser, PAID_WITH_CARD, unique="n1")
    parser.outputs[b"n1"] = output_of({**fixture(PAID_WITH_CARD)["raw"], "is_receipt": False})

    result = await service.parse(1, receipt_id)

    assert result.outcome == "not_receipt"
    assert await expense_of(make_uow, receipt_id) is None
    assert (result.card.expense_id, result.card.payment_source_name) == (None, None)
    assert await sources(make_uow) == {}


async def test_a_failed_receipt_has_no_expense(service, parser, make_uow):
    receipt_id = await intake(service, parser, PAID_WITH_CARD, unique="f1")
    parser.error = LLMError("timeout")

    assert (await service.parse(1, receipt_id)).outcome == "failed"

    assert await expense_of(make_uow, receipt_id) is None


async def test_a_duplicate_on_its_first_parse_has_no_expense_and_creates_no_source(
    service, parser, make_uow
):
    first = await intake(service, parser, PAID_WITH_CARD, unique="d1")
    second = await intake(service, parser, PAID_WITH_CARD, unique="d2")
    await service.parse(1, first)

    result = await service.parse(1, second)

    assert result.outcome == "duplicate"
    assert await expense_of(make_uow, second) is None
    assert (await expense_of(make_uow, first)).deleted_at is None
    assert result.card.expense_id is None


async def test_the_expense_is_created_in_the_receipts_transaction(
    service, parser, make_uow, monkeypatch
):
    """The expense is written after the receipt: if it fails, the parse is not stored either."""
    receipt_id = await intake(service, parser, PAID_WITH_CARD, unique="x1")
    original = SqlAlchemyExpenseRepository.add

    async def add_then_fail(self, expense):
        await original(self, expense)
        raise DatabaseException("boom")

    monkeypatch.setattr(SqlAlchemyExpenseRepository, "add", add_then_fail)
    with pytest.raises(DatabaseException):
        await service.parse(1, receipt_id)
    monkeypatch.undo()

    assert await expense_of(make_uow, receipt_id) is None
    async with make_uow() as uow:
        stored = await uow.receipts.get(receipt_id)
        catalog = await uow.catalog.get(1)
    assert stored.status is ReceiptStatus.FAILED and stored.parse is None
    assert catalog.payees == {} and catalog.payment_sources == {}


async def test_a_failing_receipt_save_leaves_no_expense(service, parser, make_uow, monkeypatch):
    receipt_id = await intake(service, parser, PAID_WITH_CARD, unique="x2")
    original = SqlAlchemyReceiptRepository.save

    async def save_parsed_then_fail(self, receipt):
        await original(self, receipt)
        if receipt.status is ReceiptStatus.PARSED:
            raise DatabaseException("boom")

    monkeypatch.setattr(SqlAlchemyReceiptRepository, "save", save_parsed_then_fail)
    with pytest.raises(DatabaseException):
        await service.parse(1, receipt_id)
    monkeypatch.undo()

    assert await expense_of(make_uow, receipt_id) is None
    assert (await service.card(1, receipt_id)).status == "failed"


# --- changes to the header -------------------------------------------------------------------


async def test_a_corrected_total_date_and_card_ending_update_the_expense(
    service, parser, make_uow, expenses
):
    receipt_id = await intake(service, parser, PAID_WITH_CARD, unique="e1")
    await service.parse(1, receipt_id)
    before = await expense_of(make_uow, receipt_id)

    await service.edit_header(1, receipt_id, "total", "9.99")
    await service.edit_header(1, receipt_id, "purchased_at", "2026-10-11T22:30:00+00:00")
    card = await service.edit_header(1, receipt_id, "card_last4", "1111")

    after = await expense_of(make_uow, receipt_id)
    assert after.id == before.id
    assert (after.amount, after.spent_at) == (D("9.99"), date(2026, 10, 12))  # 00:30 in Madrid
    assert card.payment_source_name == "VISA •1111"
    assert after.payment_source_id != before.payment_source_id
    assert await sources(make_uow) == {"0848": VISA, "1111": "VISA •1111"}
    assert (await expenses.for_receipt(1, receipt_id)).payment_source_name == "VISA •1111"


async def test_clearing_the_card_ending_moves_the_expense_to_cash(service, parser, make_uow):
    receipt_id = await intake(service, parser, PAID_WITH_CARD, unique="e2")
    await service.parse(1, receipt_id)

    card = await service.edit_header(1, receipt_id, "card_last4", None)

    assert card.payment_source_name == "Cash"
    assert (await sources(make_uow))["cash"] == "Cash"


async def test_the_category_and_the_tags_survive_a_header_edit(service, parser, make_uow, expenses):
    receipt_id = await intake(service, parser, PAID_WITH_CARD, unique="e3")
    await service.parse(1, receipt_id)
    expense = await expense_of(make_uow, receipt_id)
    await expenses.set_category(1, expense.id, "health")
    await expenses.set_tags(1, expense.id, ["pharmacy"])

    await service.edit_header(1, receipt_id, "total", "1.00")

    card = await expenses.card(1, expense.id)
    assert (card.amount, card.category, card.tags) == (D("1.00"), "health", ["pharmacy"])


async def test_an_item_edit_leaves_the_expense_alone(service, parser, make_uow):
    receipt_id = await intake(service, parser, PAID_WITH_CARD, unique="e4")
    await service.parse(1, receipt_id)
    before = await expense_of(make_uow, receipt_id)
    [ref] = [i.ref for i in (await service.items(1, receipt_id))][:1]

    await service.edit_item(1, receipt_id, ref, "discount", "0.10")

    assert await expense_of(make_uow, receipt_id) == before


async def test_correct_issue_on_the_total_updates_the_expense(service, make_uow):
    receipt = await mixed_receipt(make_uow)
    [total, *_] = await service.review(1, receipt.id)
    assert (await expense_of(make_uow, receipt.id)).amount == D("47.50")

    card = await service.correct_issue(1, receipt.id, total.issue_id, "48.10")

    assert card.total == D("48.10")
    assert (await expense_of(make_uow, receipt.id)).amount == D("48.10")


async def test_a_rejected_header_edit_changes_neither_the_receipt_nor_the_expense(
    service, parser, make_uow
):
    receipt_id = await intake(service, parser, PAID_WITH_CARD, unique="e5")
    await service.parse(1, receipt_id)
    before = await expense_of(make_uow, receipt_id)

    with pytest.raises(DataViolationError):
        await service.edit_header(
            1, receipt_id, "currency", "euros"
        )  # not a currency code: the receipt is refused

    assert await expense_of(make_uow, receipt_id) == before
    assert (await service.card(1, receipt_id)).currency == "EUR"


# --- re-parse --------------------------------------------------------------------------------


async def test_a_reparse_updates_the_expense_and_keeps_the_users_category(
    service, parser, make_uow, expenses
):
    receipt_id = await intake(service, parser, PAID_WITH_CARD, unique="r1")
    await service.parse(1, receipt_id)
    before = await expense_of(make_uow, receipt_id)
    await expenses.set_category(1, before.id, "health")
    raw = fixture(PAID_WITH_CARD)["raw"]
    raw["totals"] = {**raw["totals"], "total": 8.0}
    raw["payment"] = {**raw["payment"], "card_last4": "0048"}
    parser.outputs[b"r1"] = output_of(raw)

    await service.parse(1, receipt_id)

    after = await expense_of(make_uow, receipt_id)
    assert after.id == before.id
    assert (after.amount, after.category) == (D("8.00"), ExpenseCategory.HEALTH)
    assert after.payment_source_id != before.payment_source_id


async def test_a_reparse_that_becomes_a_duplicate_deletes_the_expense(service, parser, make_uow):
    original = await intake(service, parser, PAID_WITH_CARD, unique="u1")
    await service.parse(1, original)
    other = await intake(service, parser, UNSEEN_CARD, unique="u2")
    await service.parse(1, other)
    assert (await expense_of(make_uow, other)).deleted_at is None
    parser.outputs[b"u2"] = parser.outputs[b"u1"]

    result = await service.parse(1, other)

    assert result.outcome == "duplicate"
    gone = await expense_of(make_uow, other)
    assert gone is not None and gone.deleted_at is not None
    assert (await expense_of(make_uow, original)).deleted_at is None
    assert result.card.expense_id == gone.id


async def test_a_reparse_that_is_not_a_receipt_deletes_the_expense_and_a_later_one_restores_it(
    service, parser, make_uow, expenses
):
    receipt_id = await intake(service, parser, PAID_WITH_CARD, unique="b1")
    await service.parse(1, receipt_id)
    before = await expense_of(make_uow, receipt_id)
    await expenses.set_category(1, before.id, "gifts")
    parser.outputs[b"b1"] = output_of({**fixture(PAID_WITH_CARD)["raw"], "is_receipt": False})

    await service.parse(1, receipt_id)

    assert (await expense_of(make_uow, receipt_id)).deleted_at is not None
    parser.outputs[b"b1"] = output_of(fixture(PAID_WITH_CARD)["raw"])

    await service.parse(1, receipt_id)

    restored = await expense_of(make_uow, receipt_id)
    assert restored.id == before.id and restored.deleted_at is None
    assert (restored.amount, restored.category) == (D("7.58"), ExpenseCategory.GIFTS)


async def test_a_failed_reparse_leaves_the_expense_as_it_was(service, parser, make_uow):
    receipt_id = await intake(service, parser, PAID_WITH_CARD, unique="q1")
    await service.parse(1, receipt_id)
    before = await expense_of(make_uow, receipt_id)
    parser.error = LLMError("timeout")

    await service.parse(1, receipt_id)

    assert await expense_of(make_uow, receipt_id) == before


# --- delete ----------------------------------------------------------------------------------


async def test_deleting_the_receipt_deletes_its_expense(service, parser, make_uow, expenses):
    receipt_id = await intake(service, parser, PAID_WITH_CARD, unique="del1")
    await service.parse(1, receipt_id)

    await service.soft_delete(1, receipt_id)

    expense = await expense_of(make_uow, receipt_id)
    assert expense.deleted_at is not None
    assert (await expenses.card(1, expense.id)).deleted is True
    assert (await service.card(1, receipt_id)).deleted is True
    page = await expenses.history(1, 2026, 10)
    assert page.rows == []


async def test_deleting_a_receipt_without_an_expense_is_fine(service, parser, make_uow):
    receipt_id = await intake(service, parser, PAID_WITH_CARD, unique="del2")

    await service.soft_delete(1, receipt_id)

    assert await expense_of(make_uow, receipt_id) is None


async def test_a_seeded_receipt_syncs_on_edit_like_a_parsed_one(service, make_uow):
    receipt = await parsed_receipt(make_uow, parse(MILK, total=D("1.20")))

    await service.edit_header(1, receipt.id, "total", "2.50")

    assert (await expense_of(make_uow, receipt.id)).amount == D("2.50")
