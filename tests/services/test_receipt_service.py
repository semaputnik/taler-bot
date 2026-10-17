"""ReceiptService through the Unit of Work on real Postgres. No LLM: parses are seeded by hand."""

import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from src.database.repositories.receipt import SqlAlchemyReceiptRepository
from src.domain.enums import IssueResolution, IssueSeverity, IssueSource, ProductCategory
from src.domain.parse import Parse, ParsedIssue
from src.domain.receipt import Receipt
from src.exception import (
    DatabaseException,
    DuplicatePhoto,
    InvalidEdit,
    InvalidIssueResolution,
    InvalidReceiptTransition,
    ReceiptNotFound,
    UnknownIssue,
    UserNotFound,
)
from src.integration.storage import StorageError
from src.services.receipt import PAGE_SIZE, ReceiptService, _apply_parse
from src.services.results import Compared, NewPhoto
from tests.domain.builders import WHEN, parse, photo, product
from tests.helpers import MakeUow, add_allowed_user, add_receipt, seed_catalog
from tests.stubs import StubReceiptParser

MILK = product("mercadona::leche", total="1.20")
BREAD = product("mercadona::pan", total="2.00")
KEY = "mercadona|0042|2026-10-14|47.50"


def new_photo(unique_id: str = "u1", **fields) -> NewPhoto:
    return NewPhoto(
        received_at=WHEN,
        telegram_file_unique_id=unique_id,
        **fields,
    )


async def parsed_receipt(make_uow: MakeUow, bought: Parse, *, user_id: int = 1) -> Receipt:
    """A receipt with this parse applied, its stores and products in the catalog."""
    await seed_catalog(make_uow, bought, user_id=user_id)
    receipt = Receipt.start(user_id, photo(f"seed{user_id}"))
    receipt.apply_parse(bought)
    return await add_receipt(make_uow, receipt)


async def reparse(make_uow: MakeUow, receipt_id: int, bought: Parse) -> None:
    """Drive the private parse path the future `parse` will use, in its own Unit of Work."""
    async with make_uow() as uow:
        receipt = await uow.receipts.get(receipt_id)
        assert receipt is not None
        await _apply_parse(uow, receipt, bought)
        await uow.commit()


async def load(make_uow: MakeUow, receipt_id: int) -> Receipt:
    async with make_uow() as uow:
        receipt = await uow.receipts.get(receipt_id)
    assert receipt is not None
    return receipt


async def product_keys(make_uow: MakeUow) -> set[str]:
    async with make_uow() as uow:
        return set((await uow.catalog.get(1)).products)


@pytest.fixture
async def service(make_uow: MakeUow, tmp_storage) -> ReceiptService:
    await add_allowed_user(make_uow, 1)
    return ReceiptService(make_uow, tmp_storage, StubReceiptParser())


async def test_save_photo_starts_a_pending_receipt(service):
    card = await service.save_photo(1, b"img", new_photo())

    assert (card.status, card.item_count, card.open_issue_count) == ("pending", 0, 0)
    assert card.store_name is None


def stored_files(storage) -> list[str]:
    root = storage._root
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


async def test_save_photo_writes_the_file_under_the_users_local_date(
    service, tmp_storage, make_uow, connection
):
    await connection.execute(text("update users set timezone = 'Asia/Tokyo' where id = 1"))
    photo_in = new_photo(telegram_message_id=77, mime_type="image/png")

    card = await service.save_photo(1, b"png-bytes", photo_in)

    # 2026-10-14 18:32 UTC is 2026-10-15 03:32 in Tokyo.
    expected = "2026/10/receipt_2026-10-15_03-32-00_77.png"
    assert stored_files(tmp_storage) == [expected]
    assert await tmp_storage.read(expected) == b"png-bytes"
    assert (await load(make_uow, card.receipt_id)).photo.path == expected
    assert card.status == "pending"


@pytest.mark.parametrize(
    ("mime_type", "ext"),
    [("image/jpeg", "jpg"), ("image/webp", "webp"), ("image/heic", "jpg"), (None, "jpg")],
)
async def test_the_extension_follows_the_mime_type(service, tmp_storage, mime_type, ext):
    await service.save_photo(1, b"x", new_photo(mime_type=mime_type))

    # The default timezone is Europe/Madrid (UTC+2 in October); no message id gives 0.
    assert stored_files(tmp_storage) == [f"2026/10/receipt_2026-10-14_20-32-00_0.{ext}"]


async def test_a_duplicate_telegram_photo_writes_nothing_to_disk(service, tmp_storage):
    await service.save_photo(1, b"x", new_photo("u1", telegram_message_id=1))
    before = stored_files(tmp_storage)

    with pytest.raises(DuplicatePhoto):
        await service.save_photo(1, b"x", new_photo("u1", telegram_message_id=2))

    assert stored_files(tmp_storage) == before


async def test_a_database_failure_after_the_write_leaves_the_file_and_logs_a_warning(
    make_uow, tmp_storage, caplog
):
    await add_allowed_user(make_uow, 1)
    calls = 0

    def failing_commit_uow():
        nonlocal calls
        calls += 1
        uow = make_uow()
        if calls == 2:  # the second Unit of Work is the one that starts the receipt

            async def commit() -> None:
                raise DatabaseException("boom")

            uow.commit = commit  # type: ignore[method-assign]
        return uow

    service = ReceiptService(failing_commit_uow, tmp_storage, StubReceiptParser())

    with pytest.raises(DatabaseException), caplog.at_level("WARNING"):
        await service.save_photo(1, b"x", new_photo(telegram_message_id=5))

    expected = "2026/10/receipt_2026-10-14_20-32-00_5.jpg"
    assert stored_files(tmp_storage) == [expected]
    assert expected in caplog.text


async def test_the_same_telegram_photo_twice_is_rejected_with_no_new_rows(service, connection):
    await service.save_photo(1, b"img", new_photo("u1"))
    with pytest.raises(DuplicatePhoto):
        await service.save_photo(1, b"img", new_photo("u1"))

    assert await connection.scalar(text("select count(*) from receipts")) == 1
    assert await connection.scalar(text("select count(*) from receipt_photos")) == 1


async def test_edit_item_returns_the_updated_card_and_survives(service, make_uow):
    receipt = await parsed_receipt(make_uow, parse(MILK, total="1.20"))

    card = await service.edit_item(1, receipt.id, "mercadona::leche#1", "line_total", "1.50")

    assert card.receipt_id == receipt.id
    stored = await load(make_uow, receipt.id)
    assert stored.items[0].line_total == Decimal("1.50")
    assert [e.field for e in stored.edits] == ["line_total"]


async def test_edit_header_changes_the_card(service, make_uow):
    receipt = await parsed_receipt(make_uow, parse(MILK))

    card = await service.edit_header(1, receipt.id, "total", "9.99")

    assert str(card.total) == "9.99"


async def test_card_shows_store_name_payment_and_counts(service, make_uow):
    receipt = await parsed_receipt(
        make_uow, parse(MILK, BREAD, payment_method="card", card_brand="VISA", card_last4="1234")
    )

    card = await service.card(1, receipt.id)

    assert card.store_name == "Mercadona"
    assert (card.currency, str(card.total)) == ("EUR", "47.50")
    assert (card.payment_method, card.card_brand, card.card_last4) == ("card", "VISA", "1234")
    assert (card.item_count, card.status) == (2, "parsed")


async def test_resolve_issue_returns_the_card_with_no_open_issue(service, make_uow):
    receipt = await parsed_receipt(make_uow, parse(MILK, issues=(ParsedIssue(message="odd"),)))
    assert (await service.card(1, receipt.id)).open_issue_count == 1
    issue_id = (await load(make_uow, receipt.id)).issues[0].id

    card = await service.resolve_issue(1, receipt.id, issue_id, IssueResolution.CONFIRMED)

    assert card.open_issue_count == 0


async def test_soft_delete_hides_the_receipt_from_find_by_key(service, make_uow):
    receipt = await parsed_receipt(make_uow, parse(MILK))
    async with make_uow() as uow:
        assert await uow.receipts.find_by_key(1, KEY) is not None

    await service.soft_delete(1, receipt.id)

    async with make_uow() as uow:
        assert await uow.receipts.find_by_key(1, KEY) is None


async def test_another_users_receipt_is_not_found(service, make_uow):
    await add_allowed_user(make_uow, 2)
    mine = await service.save_photo(1, b"img", new_photo("u1"))

    for call in (
        service.card(2, mine.receipt_id),
        service.edit_header(2, mine.receipt_id, "total", "1"),
        service.soft_delete(2, mine.receipt_id),
    ):
        with pytest.raises(ReceiptNotFound):
            await call


async def test_a_missing_receipt_is_not_found(service):
    with pytest.raises(ReceiptNotFound):
        await service.card(1, 12345)


async def test_a_reparse_removes_a_product_only_the_old_parse_introduced(service, make_uow):
    receipt = await parsed_receipt(make_uow, parse(MILK))
    await reparse(make_uow, receipt.id, parse(MILK, BREAD))
    assert await product_keys(make_uow) == {"mercadona::leche", "mercadona::pan"}

    await reparse(make_uow, receipt.id, parse(MILK))

    assert await product_keys(make_uow) == {"mercadona::leche"}


async def test_a_reparse_keeps_a_product_another_receipt_also_uses(service, make_uow):
    receipt = await parsed_receipt(make_uow, parse(MILK))
    await reparse(make_uow, receipt.id, parse(MILK, BREAD))
    other = Receipt.start(1, photo("other"))
    other.apply_parse(parse(BREAD, receipt_key="k2"))
    await add_receipt(make_uow, other)

    await reparse(make_uow, receipt.id, parse(MILK))

    assert "mercadona::pan" in await product_keys(make_uow)


# --- soft_delete and the card of a deleted or duplicate receipt ---------------------------


async def stored_receipt(service) -> int:
    """A receipt saved through the service, so its photo really is in the storage."""
    card = await service.save_photo(1, b"img", new_photo())
    return card.receipt_id


async def test_soft_delete_sets_deleted_at_and_trashes_the_file(service, tmp_storage, make_uow):
    receipt_id = await stored_receipt(service)
    (path,) = stored_files(tmp_storage)
    async with make_uow() as uow:
        receipt = await uow.receipts.get(receipt_id)
        receipt.mark_failed("x")
        await uow.receipts.save(receipt)
        await uow.commit()

    await service.soft_delete(1, receipt_id)

    assert (await load(make_uow, receipt_id)).deleted_at is not None
    assert stored_files(tmp_storage) == [f".trash/{path}"]


async def test_a_failing_trash_still_leaves_the_receipt_deleted(
    service, tmp_storage, make_uow, caplog
):
    receipt_id = await stored_receipt(service)

    async def broken(relative_path: str) -> None:
        raise StorageError("disk full")

    tmp_storage.trash = broken
    with caplog.at_level(logging.WARNING):
        await service.soft_delete(1, receipt_id)

    assert (await load(make_uow, receipt_id)).deleted_at is not None
    assert any(r.levelno == logging.WARNING for r in caplog.records)
    assert len(stored_files(tmp_storage)) == 1


async def test_a_parsing_receipt_cannot_be_deleted(service, tmp_storage, make_uow):
    receipt_id = await stored_receipt(service)
    async with make_uow() as uow:
        receipt = await uow.receipts.get(receipt_id)
        receipt.mark_parsing()
        await uow.receipts.save(receipt)
        await uow.commit()

    with pytest.raises(InvalidReceiptTransition):
        await service.soft_delete(1, receipt_id)

    assert (await load(make_uow, receipt_id)).deleted_at is None
    assert not any(p.startswith(".trash") for p in stored_files(tmp_storage))


async def test_the_card_of_a_deleted_receipt_says_so(service, make_uow):
    receipt = await parsed_receipt(make_uow, parse(MILK))
    assert (await service.card(1, receipt.id)).deleted is False

    await service.soft_delete(1, receipt.id)

    assert (await service.card(1, receipt.id)).deleted is True


async def test_the_card_carries_the_photo_time(service):
    card = await service.save_photo(1, b"img", new_photo())

    assert card.received_at == WHEN


async def test_the_card_of_a_duplicate_names_the_original(service, make_uow):
    original = await parsed_receipt(make_uow, parse(MILK))
    again = Receipt.start(1, photo("seed-again"))
    again.apply_parse(parse(MILK), same_key_as=original.id)
    again = await add_receipt(make_uow, again)

    card = await service.card(1, again.id)

    assert card.status == "duplicate"
    assert card.duplicate_of is not None
    assert (card.duplicate_of.receipt_id, card.duplicate_of.store_name) == (
        original.id,
        "Mercadona",
    )
    assert card.duplicate_of.duplicate_of is None
    assert (await service.card(1, original.id)).duplicate_of is None


# --- items -----------------------------------------------------------------------------


async def test_items_come_in_parse_order_with_an_edit_applied(service, make_uow):
    receipt = await parsed_receipt(make_uow, parse(MILK, BREAD, total="3.20"))
    await service.edit_item(1, receipt.id, "mercadona::pan#1", "line_total", "2.50")

    rows = await service.items(1, receipt.id)

    assert [r.ref for r in rows] == ["mercadona::leche#1", "mercadona::pan#1"]
    assert [str(r.line_total) for r in rows] == ["1.20", "2.50"]
    first = rows[0]
    assert (first.printed_name, first.readable_name) == ("LECHE", "Leche")
    assert (first.category, first.quantity, first.unit) == ("dairy", Decimal(1), "pcs")


async def test_items_of_another_users_receipt_are_not_found(service, make_uow):
    await add_allowed_user(make_uow, 2)
    receipt = await parsed_receipt(make_uow, parse(MILK))

    with pytest.raises(ReceiptNotFound):
        await service.items(2, receipt.id)


async def test_a_deleted_receipt_still_returns_its_items(service, make_uow):
    receipt = await parsed_receipt(make_uow, parse(MILK, BREAD))
    await service.soft_delete(1, receipt.id)

    assert len(await service.items(1, receipt.id)) == 2


async def test_a_receipt_without_items_returns_an_empty_list(service):
    card = await service.save_photo(1, b"img", new_photo())

    assert await service.items(1, card.receipt_id) == []


# --- the stored photo ----------------------------------------------------------------------


async def test_photo_returns_the_stored_telegram_ids(service):
    card = await service.save_photo(
        1, b"img", new_photo(telegram_file_id="tg-file", mime_type="image/png")
    )

    ref = await service.photo(1, card.receipt_id)

    assert (ref.telegram_file_id, ref.mime_type) == ("tg-file", "image/png")


async def test_photo_bytes_returns_the_saved_bytes(service):
    card = await service.save_photo(1, b"the-bytes", new_photo())

    assert await service.photo_bytes(1, card.receipt_id) == b"the-bytes"


async def test_photo_bytes_of_a_vanished_file_is_a_storage_error(service, tmp_storage):
    card = await service.save_photo(1, b"img", new_photo())
    (path,) = stored_files(tmp_storage)
    (tmp_storage._root / path).unlink()

    with pytest.raises(StorageError):
        await service.photo_bytes(1, card.receipt_id)


async def test_another_users_photo_is_not_found(service, make_uow):
    await add_allowed_user(make_uow, 2)
    mine = await service.save_photo(1, b"img", new_photo())

    for call in (service.photo(2, mine.receipt_id), service.photo_bytes(2, mine.receipt_id)):
        with pytest.raises(ReceiptNotFound):
            await call


# --- issue review ----------------------------------------------------------------------


def mixed_issues() -> tuple[ParsedIssue, ...]:
    return (
        ParsedIssue(severity=IssueSeverity.LOW, field="receipt.register", message="low note"),
        ParsedIssue(
            severity=IssueSeverity.MEDIUM,
            field="items.name_raw",
            item_name="LECHE",
            message="unclear name",
        ),
        ParsedIssue(
            source=IssueSource.WORKFLOW,
            severity=IssueSeverity.HIGH,
            issue_type="total_mismatch",
            field="totals.total",
            message="lines do not add up",
        ),
        ParsedIssue(
            severity=IssueSeverity.MEDIUM,
            field="items.line_total",
            item_name="PAN",
            message="line math is off",
        ),
        ParsedIssue(severity=IssueSeverity.MEDIUM, field="store.address", message="no address"),
    )


async def mixed_receipt(make_uow: MakeUow) -> Receipt:
    return await parsed_receipt(make_uow, parse(MILK, BREAD, issues=mixed_issues()))


async def test_review_lists_reviewable_issues_in_walk_order_with_what_can_be_done(
    service, make_uow
):
    receipt = await mixed_receipt(make_uow)

    cards = await service.review(1, receipt.id)

    assert [c.message for c in cards] == [
        "lines do not add up",
        "unclear name",
        "line math is off",
        "no address",
    ]
    total, name, line, address = cards
    assert (total.severity, total.source, total.issue_type) == (
        "high",
        "workflow",
        "total_mismatch",
    )
    assert (total.editable, total.input_kind, total.current_value) == (
        True,
        "money",
        Decimal("47.50"),
    )
    assert (name.editable, name.input_kind, name.current_value) == (False, None, None)
    assert (name.item_name, name.field) == ("Leche", "items.name_raw")
    assert (line.editable, line.input_kind, line.current_value) == (True, "money", Decimal("2.00"))
    assert line.item_name == "Pan"
    assert (address.editable, address.item_name) == (False, None)


async def test_review_shows_the_current_value_with_edits_applied(service, make_uow):
    receipt = await mixed_receipt(make_uow)
    await service.edit_header(1, receipt.id, "total", "50.00")

    [total, *_] = await service.review(1, receipt.id)

    assert total.current_value == Decimal("50.00")


async def test_review_leaves_out_resolved_issues_but_keeps_skipped_ones(service, make_uow):
    receipt = await mixed_receipt(make_uow)
    [total, name, *_] = await service.review(1, receipt.id)
    await service.resolve_issue(1, receipt.id, total.issue_id, "confirmed")
    await service.resolve_issue(1, receipt.id, name.issue_id, "skipped")

    ids = [c.issue_id for c in await service.review(1, receipt.id)]
    assert total.issue_id not in ids
    assert name.issue_id in ids


async def test_review_of_a_receipt_without_issues_is_empty(service, make_uow):
    receipt = await parsed_receipt(make_uow, parse(MILK))
    assert await service.review(1, receipt.id) == []


async def test_card_counts_the_reviewable_issues(service, make_uow):
    receipt = await mixed_receipt(make_uow)

    card = await service.card(1, receipt.id)

    assert (card.review_count, card.open_issue_count) == (4, 5)


async def test_correct_issue_stores_the_edit_and_the_resolution_and_returns_the_card(
    service, make_uow
):
    receipt = await mixed_receipt(make_uow)
    [total, *_] = await service.review(1, receipt.id)

    card = await service.correct_issue(1, receipt.id, total.issue_id, Decimal("48.10"))

    assert (card.total, card.review_count, card.open_issue_count) == (Decimal("48.10"), 3, 4)
    stored = await load(make_uow, receipt.id)
    assert stored.header.total == Decimal("48.10")
    [edit] = stored.edits
    assert (edit.field, edit.issue_id) == ("total", total.issue_id)
    resolved = next(i for i in stored.issues if i.id == total.issue_id)
    assert resolved.resolution is IssueResolution.CORRECTED
    assert resolved.resolved_at is not None


async def test_correct_issue_changes_the_item_the_issue_is_about(service, make_uow):
    receipt = await mixed_receipt(make_uow)
    line = (await service.review(1, receipt.id))[2]

    await service.correct_issue(1, receipt.id, line.issue_id, "2.40")

    stored = await load(make_uow, receipt.id)
    assert [i.line_total for i in stored.items] == [Decimal("1.20"), Decimal("2.40")]
    assert stored.edits[0].item_ref == "mercadona::pan#1"


async def test_correct_issue_with_a_bad_value_changes_nothing(service, make_uow):
    receipt = await mixed_receipt(make_uow)
    [total, *_] = await service.review(1, receipt.id)

    with pytest.raises(InvalidEdit):
        await service.correct_issue(1, receipt.id, total.issue_id, "abc")

    stored = await load(make_uow, receipt.id)
    assert stored.edits == []
    assert len(stored.reviewable_issues()) == 4


async def test_correct_issue_refuses_a_field_that_cannot_be_typed(service, make_uow):
    receipt = await mixed_receipt(make_uow)
    name = (await service.review(1, receipt.id))[1]

    with pytest.raises(InvalidEdit):
        await service.correct_issue(1, receipt.id, name.issue_id, "Milk")


async def test_correct_issue_refuses_unknown_and_resolved_issues(service, make_uow):
    receipt = await mixed_receipt(make_uow)
    [total, *_] = await service.review(1, receipt.id)
    await service.resolve_issue(1, receipt.id, total.issue_id, "confirmed")

    with pytest.raises(InvalidIssueResolution):
        await service.correct_issue(1, receipt.id, total.issue_id, "1")
    with pytest.raises(UnknownIssue):
        await service.correct_issue(1, receipt.id, 987654, "1")


async def test_a_failing_save_leaves_neither_the_edit_nor_the_resolution(
    service, make_uow, monkeypatch
):
    receipt = await mixed_receipt(make_uow)
    [total, *_] = await service.review(1, receipt.id)
    original = SqlAlchemyReceiptRepository.save

    async def save_then_fail(self, receipt):
        await original(self, receipt)
        raise DatabaseException("boom")

    monkeypatch.setattr(SqlAlchemyReceiptRepository, "save", save_then_fail)
    with pytest.raises(DatabaseException):
        await service.correct_issue(1, receipt.id, total.issue_id, "48.10")
    monkeypatch.undo()

    stored = await load(make_uow, receipt.id)
    assert stored.edits == []
    assert stored.header.total == Decimal("47.50")
    assert len(stored.reviewable_issues()) == 4


async def test_review_and_correct_issue_of_another_users_receipt_are_not_found(service, make_uow):
    receipt = await mixed_receipt(make_uow)
    [total, *_] = await service.review(1, receipt.id)
    await add_allowed_user(make_uow, 2)

    with pytest.raises(ReceiptNotFound):
        await service.review(2, receipt.id)
    with pytest.raises(ReceiptNotFound):
        await service.correct_issue(2, receipt.id, total.issue_id, "1")


async def test_item_rows_carry_the_product_key(service, make_uow):
    receipt = await parsed_receipt(make_uow, parse(MILK, BREAD))

    rows = await service.items(1, receipt.id)

    assert [r.product_key for r in rows] == ["mercadona::leche", "mercadona::pan"]


async def test_review_cards_carry_the_product_key_and_whether_the_name_can_be_renamed(
    service, make_uow
):
    receipt = await mixed_receipt(make_uow)

    total, name, line, address = await service.review(1, receipt.id)

    assert (name.product_key, name.renamable) == ("mercadona::leche", True)
    assert (line.product_key, line.renamable) == ("mercadona::pan", False)
    assert (total.product_key, total.renamable) == (None, False)
    assert (address.product_key, address.renamable) == (None, False)


async def test_a_name_issue_without_a_matched_item_is_not_renamable(service, make_uow):
    ghost = ParsedIssue(
        severity=IssueSeverity.MEDIUM,
        field="items.name_normalized",
        item_name="NOT ON THE RECEIPT",
        message="ambiguous",
    )
    receipt = await parsed_receipt(make_uow, parse(MILK, issues=(ghost,)))

    [card] = await service.review(1, receipt.id)

    assert (card.product_key, card.renamable) == (None, False)


async def test_a_normalized_name_issue_with_a_matched_item_is_renamable(service, make_uow):
    issue = ParsedIssue(
        severity=IssueSeverity.MEDIUM,
        field="items.name_normalized",
        item_name="LECHE",
        message="ambiguous",
    )
    receipt = await parsed_receipt(make_uow, parse(MILK, issues=(issue,)))

    [card] = await service.review(1, receipt.id)

    assert (card.product_key, card.renamable) == ("mercadona::leche", True)


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


async def test_history_uses_the_users_time_zone(service, make_uow, connection):
    await bought_on(make_uow, 1, datetime(2026, 10, 31, 23, 30, tzinfo=UTC))

    madrid = await service.history(1, 2026, 11)
    assert [r.day for r in madrid.rows] == [date(2026, 11, 1)]
    assert (await service.history(1, 2026, 10)).rows == []

    await connection.execute(text("update users set timezone = 'UTC' where id = 1"))
    utc = await service.history(1, 2026, 10)
    assert [r.day for r in utc.rows] == [date(2026, 10, 31)]


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


async def test_another_users_store_id_yields_an_empty_page(service, make_uow):
    await add_allowed_user(make_uow, 2)
    await bought_on(make_uow, 1, datetime(2026, 10, 10, 12, tzinfo=UTC))
    await bought_on(make_uow, 2, datetime(2026, 10, 10, 12, tzinfo=UTC), user_id=2)
    async with make_uow() as uow:
        theirs = (await uow.catalog.get(2)).payees["mercadona"].id

    page = await service.history(1, 2026, 10, store_id=theirs)

    assert (page.rows, page.total_rows, page.parsed_count, page.totals) == ([], 0, 0, [])
    assert page.store_name is None
    assert len(page.stores) == 1


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
    assert (block.currency, block.total, block.receipt_count) == ("EUR", D("150.00"), 2)
    assert block.previous_total == D("170.00")
    assert block.change == -12
    meat, dairy = block.categories
    assert (meat.key, meat.value, meat.share, meat.previous, meat.change) == (
        "meat",
        D("120.00"),
        80,
        D("100.00"),
        20,
    )
    assert (dairy.key, dairy.share, dairy.previous, dairy.change) == ("dairy", 20, D("60.00"), -50)
    assert [(x.label, x.change) for x in block.stores] == [("A", 20), ("B", -50)]
    assert [(x.label, x.share) for x in block.cards] == [("VISA •0848", 80), ("", 20)]
    assert [x.key for x in block.cards] == ["0848", "cash"]


async def test_a_line_without_a_previous_value_is_new_and_a_zero_previous_has_no_change(
    service, make_uow
):
    await spent(make_uow, october(), "50.00", category=ProductCategory.MEAT, store="a")
    await spent(make_uow, october(11), "20.00", category=ProductCategory.PET, store="b")
    await spent(make_uow, september(), "10.00", category=ProductCategory.MEAT, store="a")
    await spent(make_uow, september(11), "0.00", category=ProductCategory.PET, store="b")

    [block] = (await service.spending(1, "month", date(2026, 10, 14))).blocks

    pet = line(block.categories, "pet")
    assert (pet.previous, pet.change) == (None, None)  # not in the previous period's lines
    shop_b = block.stores[1]
    assert (shop_b.label, shop_b.previous, shop_b.change) == ("B", D("0.00"), None)
    assert line(block.categories, "meat").change == 400


async def test_a_currency_new_this_period_has_no_previous_total(service, make_uow):
    await spent(make_uow, october(), "50.00")
    await spent(make_uow, september(), "10.00", currency="USD")

    [block] = (await service.spending(1, "month", date(2026, 10, 14))).blocks

    assert (block.previous_total, block.change) == (None, None)
    assert {x.previous for x in block.categories} == {None}


async def test_shares_sum_to_about_a_hundred_with_not_itemised_included(service, make_uow):
    await spent(make_uow, october(), "10.00", category=ProductCategory.MEAT)
    await spent(make_uow, october(), "10.00", category=ProductCategory.DAIRY)
    await spent(make_uow, october(), "10.00", category=ProductCategory.PET, total="13.00")

    [block] = (await service.spending(1, "month", date(2026, 10, 14))).blocks

    assert block.total == D("33.00")
    assert [x.share for x in block.categories if x.key != "not_itemised"] == [30, 30, 30]
    extra = line(block.categories, "not_itemised")
    assert (extra.value, extra.share, extra.label) == (D("3.00"), 9, "")
    assert block.categories[-1] is extra
    assert abs(sum(x.share for x in block.categories) - 100) <= 2


async def test_a_negligible_not_itemised_remainder_is_left_out(service, make_uow):
    await spent(make_uow, october(), "10.00")

    [block] = (await service.spending(1, "month", date(2026, 10, 14))).blocks

    assert [x.key for x in block.categories] == ["dairy"]


async def test_only_the_five_largest_stores_are_kept(service, make_uow):
    for n in range(7):
        await spent(make_uow, october(), f"{10 + n}.00", store=f"shop{n}")

    [block] = (await service.spending(1, "month", date(2026, 10, 14))).blocks

    assert [x.label for x in block.stores] == ["Shop6", "Shop5", "Shop4", "Shop3", "Shop2"]
    assert block.receipt_count == 7


async def test_the_users_currency_comes_first_then_alphabetical(service, make_uow, connection):
    await spent(make_uow, october(), "5.00", currency="EUR")
    await spent(make_uow, october(), "5.00", currency="USD", store="us")
    await spent(make_uow, october(), "5.00", currency="GBP", store="uk")

    eur_first = await service.spending(1, "month", date(2026, 10, 14))
    await connection.execute(text("update users set default_currency = 'USD' where id = 1"))
    usd_first = await service.spending(1, "month", date(2026, 10, 14))

    assert [b.currency for b in eur_first.blocks] == ["EUR", "GBP", "USD"]
    assert [b.currency for b in usd_first.blocks] == ["USD", "EUR", "GBP"]


async def test_has_earlier_looks_for_a_parsed_receipt_before_the_period(service, make_uow):
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


async def test_spending_uses_the_users_time_zone(service, make_uow, connection):
    await spent(make_uow, datetime(2026, 10, 31, 23, 30, tzinfo=UTC), "5.00")

    in_madrid = await service.spending(1, "month", date(2026, 10, 14))
    await connection.execute(text("update users set timezone = 'UTC' where id = 1"))
    in_utc = await service.spending(1, "month", date(2026, 10, 14))

    assert in_madrid.blocks == []
    assert in_utc.blocks[0].total == D("5.00")


async def test_spending_of_an_unknown_user_is_refused(service):
    with pytest.raises(UserNotFound):
        await service.spending(404, "month", date(2026, 10, 14))


async def test_spending_never_shows_another_users_receipts(service, make_uow):
    await add_allowed_user(make_uow, 2)
    await spent(make_uow, october(), "77.00", user_id=2)

    assert (await service.spending(1, "month", date(2026, 10, 14))).blocks == []
