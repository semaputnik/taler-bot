"""`ReceiptRepository` through the Unit of Work on real Postgres: whole-aggregate round trips,
lookups and the schema constraints, which must reach callers as app exceptions."""

from dataclasses import replace
from decimal import Decimal
from enum import StrEnum
from itertools import count

import pytest
from sqlalchemy import text

from src.domain.edits import Edit
from src.domain.enums import EditTarget, IssueResolution, IssueSeverity, ReceiptStatus
from src.domain.parse import ParsedIssue
from src.domain.receipt import Header, Photo, Receipt
from src.exception import (
    CheckViolationError,
    DataViolationError,
    ForeignKeyViolationError,
    UniqueViolationError,
)
from tests.domain.builders import WHEN, parse, photo, product
from tests.helpers import MakeUow, add_user, seed_catalog

MILK = product("mercadona::leche", total="1.20")
BREAD = product("mercadona::pan", total="0.90")


async def persist(make_uow: MakeUow, receipt: Receipt) -> Receipt:
    async with make_uow() as uow:
        receipt = await uow.receipts.add(receipt)
        await uow.commit()
    return receipt


async def load(make_uow: MakeUow, receipt_id: int | None) -> Receipt:
    async with make_uow() as uow:
        loaded = await uow.receipts.get(receipt_id)
    assert loaded is not None
    return loaded


async def test_a_receipt_with_a_photo_parse_items_issue_and_edit_round_trips(make_uow):
    one = parse(
        MILK,
        BREAD,
        issues=(
            ParsedIssue(
                issue_type="missing_total", severity=IssueSeverity.HIGH, message="No total"
            ),
        ),
    )
    await add_user(make_uow)
    await seed_catalog(make_uow, one)
    receipt = Receipt.start(1, photo("u1"))
    receipt.apply_parse(one)
    receipt.record_edit(Edit(target=EditTarget.RECEIPT, field="total", value="9.50"))

    added = await persist(make_uow, receipt)

    assert added is receipt
    assert added.id is not None
    assert added.photo.id is not None
    assert added.parse is not None
    assert added.parse.id is not None
    assert all(i.id is not None for i in added.issues)
    assert all(e.id is not None for e in added.edits)
    assert not added.parse_changed
    assert await load(make_uow, added.id) == added


async def seeded_receipt(make_uow: MakeUow, *parses) -> Receipt:
    """A stored receipt with one photo and the given parses applied in order (re-parses)."""
    await add_user(make_uow)
    await seed_catalog(make_uow, *parses)
    receipt = Receipt.start(1, photo("u1"))
    for p in parses:
        receipt.apply_parse(p)
    return await persist(make_uow, receipt)


async def change(make_uow: MakeUow, receipt_id: int | None, act) -> Receipt:
    """Load, let `act` change the aggregate, save and commit; return the aggregate as saved."""
    async with make_uow() as uow:
        receipt = await uow.receipts.get(receipt_id)
        act(receipt)
        await uow.receipts.save(receipt)
        await uow.commit()
    return receipt


async def test_a_re_parse_keeps_one_parse_row_and_replaces_items_and_issues(make_uow):
    first = parse(MILK, BREAD, issues=(ParsedIssue(issue_type="blurry", message="Blurry"),))
    second = parse(
        BREAD,
        parser_version="2026-11-01.1",
        issues=(ParsedIssue(issue_type="odd", message="Odd total"),),
    )
    saved = await seeded_receipt(make_uow, first)
    await seed_catalog(make_uow, second)
    await change(
        make_uow,
        saved.id,
        lambda r: r.record_edit(Edit(target=EditTarget.RECEIPT, field="currency", value="USD")),
    )
    before = await load(make_uow, saved.id)

    receipt = await change(make_uow, saved.id, lambda r: r.apply_parse(second))

    after = await load(make_uow, saved.id)
    assert after == receipt
    assert after.parse.id == before.parse.id
    assert after.parse == replace(second, id=before.parse.id)
    assert [i.product_key for i in after.items] == ["mercadona::pan"]
    assert [i.issue_type for i in after.issues] == ["odd", "edit_conflict"]
    assert after.photo == before.photo
    assert after.edits == before.edits


async def test_a_re_parse_to_not_a_receipt_clears_the_items(make_uow):
    saved = await seeded_receipt(make_uow, parse(MILK))

    receipt = await change(
        make_uow, saved.id, lambda r: r.apply_parse(parse(is_receipt=False, items=()))
    )

    loaded = await load(make_uow, saved.id)
    assert loaded == receipt
    assert loaded.status is ReceiptStatus.NOT_RECEIPT
    assert loaded.items == []


async def test_the_first_parse_of_a_stored_receipt_inserts_the_parse_row(make_uow):
    one = parse(MILK)
    await add_user(make_uow)
    await seed_catalog(make_uow, one)
    saved = await persist(make_uow, Receipt.start(1, photo("u1")))
    assert saved.parse is None

    receipt = await change(make_uow, saved.id, lambda r: r.apply_parse(one))

    loaded = await load(make_uow, saved.id)
    assert loaded == receipt
    assert loaded.parse is not None
    assert loaded.parse.id is not None
    assert [i.product_key for i in loaded.items] == ["mercadona::leche"]


async def test_an_item_edit_replaces_the_items_but_keeps_issue_resolutions(make_uow):
    saved = await seeded_receipt(
        make_uow, parse(MILK, issues=(ParsedIssue(issue_type="blurry", message="Blurry"),))
    )
    issue_id = saved.issues[0].id

    def act(receipt):
        receipt.resolve_issue(issue_id, IssueResolution.CONFIRMED)

    await change(make_uow, saved.id, act)
    receipt = await change(
        make_uow,
        saved.id,
        lambda r: r.record_edit(
            Edit(
                target=EditTarget.ITEM,
                item_ref="mercadona::leche#1",
                field="quantity",
                value="3",
            )
        ),
    )

    loaded = await load(make_uow, saved.id)
    assert loaded == receipt
    assert loaded.items[0].quantity == 3
    assert loaded.issues[0].id == issue_id
    assert loaded.issues[0].resolution is IssueResolution.CONFIRMED


async def test_resolving_an_issue_updates_it_in_place(make_uow):
    saved = await seeded_receipt(
        make_uow, parse(MILK, issues=(ParsedIssue(issue_type="blurry", message="Blurry"),))
    )
    issue_id = saved.issues[0].id

    receipt = await change(
        make_uow, saved.id, lambda r: r.resolve_issue(issue_id, IssueResolution.SKIPPED)
    )

    loaded = await load(make_uow, saved.id)
    assert loaded == receipt
    assert (loaded.issues[0].id, loaded.issues[0].resolution) == (issue_id, IssueResolution.SKIPPED)


async def test_a_header_edit_is_stored_and_survives_a_new_parse(make_uow):
    saved = await seeded_receipt(make_uow, parse(MILK))
    edit = Edit(target=EditTarget.RECEIPT, field="total", value="9.50")
    await change(make_uow, saved.id, lambda r: r.record_edit(edit))

    receipt = await change(
        make_uow, saved.id, lambda r: r.apply_parse(parse(MILK, total=Decimal("40")))
    )

    loaded = await load(make_uow, saved.id)
    assert loaded == receipt
    assert loaded.header.total == Decimal("9.50")
    assert [i.issue_type for i in loaded.issues] == ["edit_conflict"]
    assert len(loaded.edits) == 1


async def test_status_changes_and_soft_delete_are_saved(make_uow):
    saved = await seeded_receipt(make_uow, parse(MILK))

    receipt = await change(make_uow, saved.id, lambda r: r.soft_delete(at=WHEN))

    loaded = await load(make_uow, saved.id)
    assert loaded == receipt
    assert loaded.deleted_at == WHEN
    assert loaded.status is ReceiptStatus.PARSED


async def test_a_failed_receipt_keeps_its_reason(make_uow):
    await add_user(make_uow)
    receipt = Receipt.start(1, photo("u1"))
    receipt.mark_failed("The model timed out")
    saved = await persist(make_uow, receipt)

    loaded = await load(make_uow, saved.id)
    assert loaded == receipt
    assert (loaded.status, loaded.error_message) == (ReceiptStatus.FAILED, "The model timed out")


async def test_a_missing_receipt_is_none(make_uow):
    async with make_uow() as uow:
        assert await uow.receipts.get(123456) is None


async def test_get_runs_a_bounded_number_of_queries(make_uow, statements):
    saved = await seeded_receipt(
        make_uow,
        parse(MILK, BREAD, MILK, issues=(ParsedIssue(issue_type="blurry", message="Blurry"),)),
    )
    statements.clear()

    await load(make_uow, saved.id)

    # One per table: receipts (+ store), photo, parse, items (+ products), issues, edits.
    assert len([s for s in statements if s.startswith("SELECT")]) == 6


# --- lookups -------------------------------------------------------------------------------

KEY = "mercadona|A-123|2026-10-14|47.85"


async def parsed_receipt(
    make_uow: MakeUow, *, user_id: int = 1, seed: bool = True, **fields
) -> Receipt:
    """A stored `parsed` receipt, built on the aggregate so its key and store are real."""
    one = parse(MILK, receipt_key=KEY, **fields)
    if seed:
        await seed_catalog(make_uow, one, user_id=user_id)
    receipt = Receipt.start(user_id, photo(f"u{user_id}-{fields.get('receipt_number', '')}"))
    receipt.apply_parse(one)
    return await persist(make_uow, receipt)


async def test_find_by_key_returns_the_parsed_receipt_and_ignores_deleted_ones(make_uow):
    await add_user(make_uow)
    saved = await parsed_receipt(make_uow)

    async with make_uow() as uow:
        found = await uow.receipts.find_by_key(1, KEY)
        assert found == await uow.receipts.get(saved.id)
        assert await uow.receipts.find_by_key(1, "other|key") is None
        assert await uow.receipts.find_by_key(2, KEY) is None

    await change(make_uow, saved.id, lambda r: r.soft_delete())
    async with make_uow() as uow:
        assert await uow.receipts.find_by_key(1, KEY) is None
        assert (await uow.receipts.get(saved.id)).deleted_at is not None


async def test_find_by_key_ignores_duplicate_receipts(make_uow):
    await add_user(make_uow)
    original = await parsed_receipt(make_uow)
    # Same key as `original`, so it cannot stay `parsed`: it becomes a duplicate of it.
    again = Receipt.start(1, photo("again"))
    again.apply_parse(parse(MILK, receipt_key=KEY))
    again.mark_duplicate(original.id)
    repeat = await persist(make_uow, again)

    async with make_uow() as uow:
        found = await uow.receipts.find_by_key(1, KEY)
        assert found is not None
        assert found.id == original.id
        loaded = await uow.receipts.get(repeat.id)
    assert loaded.status is ReceiptStatus.DUPLICATE
    assert loaded.duplicate_of_id == original.id


async def test_find_by_key_ignores_receipts_that_are_not_parsed(make_uow):
    await add_user(make_uow)
    await persist(make_uow, keyed(ReceiptStatus.PENDING))

    async with make_uow() as uow:
        assert await uow.receipts.find_by_key(1, KEY) is None


async def test_photo_exists_only_for_the_same_user(make_uow):
    await add_user(make_uow, 1)
    await add_user(make_uow, 2)
    await persist(make_uow, Receipt.start(1, photo("AQADabc")))

    async with make_uow() as uow:
        assert await uow.receipts.photo_exists(1, "AQADabc")
        assert not await uow.receipts.photo_exists(2, "AQADabc")
        assert not await uow.receipts.photo_exists(1, "other")


# --- constraints, as app exceptions --------------------------------------------------------


class Rogue(StrEnum):
    """Values the domain enums lack, to prove the CHECKs hold when the aggregate is bypassed."""

    BOGUS = "bogus"
    USER = "user"
    CRITICAL = "critical"
    IGNORED = "ignored"
    STORE = "store"


_unique = count(1)


def keyed(status: ReceiptStatus, *, user_id: int = 1, **fields) -> Receipt:
    return Receipt(
        user_id=user_id,
        status=status,
        header=Header(receipt_key=KEY),
        photo=photo(f"k{next(_unique)}"),
        **fields,
    )


def bare(status: ReceiptStatus = ReceiptStatus.PENDING, **fields) -> Receipt:
    return Receipt(user_id=1, status=status, photo=photo(f"b{next(_unique)}"), **fields)


async def test_parsed_receipt_key_is_unique_per_user(make_uow):
    await add_user(make_uow, 1)
    await add_user(make_uow, 2)
    first = await persist(make_uow, keyed(ReceiptStatus.PARSED))

    await persist(make_uow, keyed(ReceiptStatus.PARSED, user_id=2))
    await persist(make_uow, keyed(ReceiptStatus.PENDING))
    await persist(make_uow, keyed(ReceiptStatus.DUPLICATE, duplicate_of_id=first.id))
    await persist(make_uow, keyed(ReceiptStatus.PARSED, deleted_at=WHEN))
    with pytest.raises(UniqueViolationError):
        await persist(make_uow, keyed(ReceiptStatus.PARSED))


@pytest.mark.parametrize("value", ["ab12", "12 3", "123"])
async def test_card_last4_is_exactly_four_digits(make_uow, value):
    await add_user(make_uow)
    with pytest.raises(CheckViolationError):
        await persist(make_uow, bare(header=Header(card_last4=value)))


async def test_card_last4_longer_than_four_characters_is_rejected(make_uow):
    await add_user(make_uow)
    with pytest.raises(DataViolationError):
        await persist(make_uow, bare(header=Header(card_last4="12345")))


async def test_duplicate_status_goes_with_duplicate_of_id_both_ways(make_uow):
    await add_user(make_uow)
    original = await persist(make_uow, bare(ReceiptStatus.PARSED))

    repeat = await persist(make_uow, bare(ReceiptStatus.DUPLICATE, duplicate_of_id=original.id))
    assert (await load(make_uow, repeat.id)).duplicate_of_id == original.id
    with pytest.raises(CheckViolationError):
        await persist(make_uow, bare(ReceiptStatus.DUPLICATE))
    with pytest.raises(CheckViolationError):
        await persist(make_uow, bare(ReceiptStatus.PARSED, duplicate_of_id=original.id))


async def test_unknown_receipt_status_is_rejected(make_uow):
    await add_user(make_uow)
    with pytest.raises(CheckViolationError):
        await persist(make_uow, bare(Rogue.BOGUS))


@pytest.mark.parametrize(
    ("field", "value"),
    [("source", Rogue.USER), ("severity", Rogue.CRITICAL), ("resolution", Rogue.IGNORED)],
)
async def test_unknown_issue_values_are_rejected(make_uow, field, value):
    one = parse(MILK, issues=(ParsedIssue(message="Doubt"),))
    await add_user(make_uow)
    await seed_catalog(make_uow, one)
    receipt = Receipt.start(1, photo("u1"))
    receipt.apply_parse(one)
    setattr(receipt.issues[0], field, value)

    with pytest.raises(CheckViolationError):
        await persist(make_uow, receipt)


async def test_unknown_edit_target_is_rejected(make_uow):
    one = parse(MILK)
    await add_user(make_uow)
    await seed_catalog(make_uow, one)
    receipt = Receipt.start(1, photo("u1"))
    receipt.apply_parse(one)
    receipt.record_edit(Edit(target=EditTarget.RECEIPT, field="total", value="9.50"))
    receipt.edits[0].target = Rogue.STORE

    with pytest.raises(CheckViolationError):
        await persist(make_uow, receipt)


@pytest.mark.parametrize("break_it", ["item-without-ref", "receipt-with-ref"])
async def test_item_ref_goes_with_item_edits_only(make_uow, break_it):
    one = parse(MILK)
    await add_user(make_uow)
    await seed_catalog(make_uow, one)
    receipt = Receipt.start(1, photo("u1"))
    receipt.apply_parse(one)
    if break_it == "item-without-ref":
        receipt.record_edit(
            Edit(target=EditTarget.ITEM, item_ref="mercadona::leche#1", field="quantity", value=2)
        )
        receipt.edits[0].item_ref = None
    else:
        receipt.record_edit(Edit(target=EditTarget.RECEIPT, field="total", value="9.50"))
        receipt.edits[0].item_ref = "mercadona::leche#1"

    with pytest.raises(CheckViolationError):
        await persist(make_uow, receipt)


async def test_a_photo_needs_a_stored_path_or_a_drive_file(make_uow):
    await add_user(make_uow)
    with pytest.raises(CheckViolationError):
        await persist(
            make_uow,
            Receipt.start(1, Photo(telegram_file_unique_id="u1", path=None, received_at=WHEN)),
        )


async def test_the_same_telegram_photo_is_rejected_for_the_same_user_only(make_uow):
    await add_user(make_uow, 1)
    await add_user(make_uow, 2)
    await persist(make_uow, Receipt.start(1, photo("AQADabc")))

    await persist(make_uow, Receipt.start(2, photo("AQADabc")))
    with pytest.raises(UniqueViolationError):
        await persist(make_uow, Receipt.start(1, photo("AQADabc")))


async def test_photos_without_a_telegram_id_never_collide(make_uow):
    await add_user(make_uow)
    first, second = photo("x"), photo("y")
    first.telegram_file_unique_id = None
    second.telegram_file_unique_id = None
    await persist(make_uow, Receipt.start(1, first))

    saved = await persist(make_uow, Receipt.start(1, second))

    assert await load(make_uow, saved.id) == saved


async def test_a_second_photo_row_for_a_receipt_is_rejected(make_uow):
    await add_user(make_uow)
    saved = await persist(make_uow, Receipt.start(1, photo("u1")))

    async with make_uow() as uow:
        with pytest.raises(UniqueViolationError):
            await uow._session.execute(  # noqa: SLF001  the aggregate cannot hold two photos
                text(
                    "INSERT INTO receipt_photos (receipt_id, user_id, path, received_at)"
                    " VALUES (:r, 1, 'p.jpg', now())"
                ),
                {"r": saved.id},
            )


async def test_a_second_parse_row_for_a_receipt_is_rejected(make_uow):
    saved = await seeded_receipt(make_uow, parse(MILK))

    async with make_uow() as uow:
        with pytest.raises(UniqueViolationError):
            await uow._session.execute(  # noqa: SLF001  the aggregate cannot hold two parses
                text(
                    "INSERT INTO receipt_parses (receipt_id, status, parser_version)"
                    " VALUES (:r, 'ok', 'v2')"
                ),
                {"r": saved.id},
            )


async def test_items_need_their_products_in_the_catalog(make_uow):
    await add_user(make_uow)
    receipt = Receipt.start(1, photo("u1"))
    receipt.apply_parse(parse(MILK))  # no seed_catalog

    with pytest.raises(ForeignKeyViolationError):
        await persist(make_uow, receipt)


async def test_deleting_a_user_removes_their_receipts(make_uow):
    saved = await seeded_receipt(make_uow, parse(MILK, issues=(ParsedIssue(message="Doubt"),)))
    async with make_uow() as uow:
        await uow.users.delete(1)
        await uow.commit()

    async with make_uow() as uow:
        assert await uow.receipts.get(saved.id) is None


async def test_marking_a_stored_receipt_as_a_duplicate_is_saved(make_uow):
    await add_user(make_uow)
    original = await parsed_receipt(make_uow)
    one = parse(MILK, receipt_key=KEY)
    pending = await persist(make_uow, Receipt.start(1, photo("again")))

    def repeat(receipt):
        receipt.apply_parse(one)
        receipt.mark_duplicate(original.id)

    receipt = await change(make_uow, pending.id, repeat)

    loaded = await load(make_uow, pending.id)
    assert loaded == receipt
    assert (loaded.status, loaded.duplicate_of_id) == (ReceiptStatus.DUPLICATE, original.id)
