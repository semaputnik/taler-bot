"""`ReceiptRepository` through the Unit of Work on real Postgres: whole-aggregate round trips,
lookups and the schema constraints, which must reach callers as app exceptions."""

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from itertools import count

import pytest
from sqlalchemy import text

from src.database.read_models import (
    Amount,
    CurrencyBlock,
    CurrencyTotal,
    HistoryPage,
    HistoryRow,
    SpendingPeriod,
)
from src.domain.edits import Edit
from src.domain.enums import Category, EditTarget, IssueResolution, IssueSeverity, ReceiptStatus
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

SPENDING_STATEMENTS = 4  # totals, categories, stores, cards
HISTORY_STATEMENTS = 4  # rows, aggregates, totals per currency, the month's stores
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


async def test_usage_and_duration_round_trip_on_the_parse_row(make_uow):
    stamped = replace(parse(MILK), input_tokens=1200, output_tokens=340, duration_ms=8123)
    await add_user(make_uow)
    await seed_catalog(make_uow, stamped)
    receipt = Receipt.start(1, photo("usage"))
    receipt.apply_parse(stamped)

    loaded = await load(make_uow, (await persist(make_uow, receipt)).id)

    assert (loaded.parse.input_tokens, loaded.parse.output_tokens, loaded.parse.duration_ms) == (
        1200,
        340,
        8123,
    )


async def test_known_card_last4_lists_the_users_parsed_receipts_cards_only(make_uow):
    await add_user(make_uow)
    await add_user(make_uow, 2)
    for i, (user_id, last4) in enumerate([(1, "1111"), (1, "1111"), (2, "2222")]):
        bought = replace(parse(MILK, receipt_key=f"k{i}"), card_last4=last4)
        await seed_catalog(make_uow, bought, user_id=user_id)
        receipt = Receipt.start(user_id, photo(f"c{i}"))
        receipt.apply_parse(bought)
        await persist(make_uow, receipt)
    await persist(make_uow, bare())  # pending, no card

    async with make_uow() as uow:
        assert await uow.receipts.known_card_last4(1) == {"1111"}
        assert await uow.receipts.known_card_last4(2) == {"2222"}
        assert await uow.receipts.known_card_last4(3) == set()


# --- history ---------------------------------------------------------------------------------

MADRID = "Europe/Madrid"
_history_ids = count(1)


def at(day: int, hour: int = 12, *, month: int = 10, year: int = 2026) -> datetime:
    return datetime(year, month, day, hour, 0, tzinfo=UTC)


async def bought(
    make_uow: MakeUow,
    purchased_at: datetime,
    *,
    store: str = "mercadona",
    total: str = "10.00",
    currency: str = "EUR",
    deleted: bool = False,
    duplicate_of: int | None = None,
) -> Receipt:
    """A stored receipt of user 1 with this purchase date (the user is added on first use)."""
    n = next(_history_ids)
    one = parse(
        product(f"{store}::item{n}", total=total),
        store_key=store,
        store_name=store.capitalize(),
        purchased_at=purchased_at,
        receipt_number=str(n),
        receipt_key=f"{store}|{n}",
        total=Decimal(total),
        currency=currency,
    )
    await add_user(make_uow)
    await seed_catalog(make_uow, one)
    receipt = Receipt.start(1, photo(f"h{n}"))
    receipt.apply_parse(one)
    if duplicate_of is not None:
        receipt.mark_duplicate(duplicate_of)
    if deleted:
        receipt.soft_delete()
    return await persist(make_uow, receipt)


async def failed(make_uow: MakeUow, received_at: datetime) -> Receipt:
    await add_user(make_uow)
    n = next(_history_ids)
    receipt = Receipt.start(1, replace(photo(f"h{n}"), received_at=received_at))
    receipt.mark_parsing()
    receipt.mark_failed("The model timed out")
    return await persist(make_uow, receipt)


async def october(make_uow: MakeUow, **kwargs):
    async with make_uow() as uow:
        return await uow.receipts.history(1, 2026, 10, MADRID, **kwargs)


async def store_id_of(make_uow: MakeUow, key: str) -> int:
    async with make_uow() as uow:
        return (await uow.catalog.get(1)).stores[key].id


async def test_a_receipt_lands_in_the_month_of_its_purchase_date(make_uow):
    inside = await bought(make_uow, at(10))
    await bought(make_uow, at(10, month=9))
    await bought(make_uow, at(10, month=11))

    page = await october(make_uow)

    assert [r.receipt_id for r in page.rows] == [inside.id]
    assert (page.year, page.month, page.total_rows) == (2026, 10, 1)


async def test_a_receipt_without_a_purchase_date_lands_in_the_month_its_photo_was_received(
    make_uow,
):
    unread = await failed(make_uow, at(5))
    await failed(make_uow, at(5, month=9))

    page = await october(make_uow)

    assert [(r.receipt_id, r.status, r.total, r.store_name) for r in page.rows] == [
        (unread.id, "failed", None, None)
    ]
    assert page.parsed_count == 0
    assert page.totals == []


async def test_the_month_and_the_day_are_those_of_the_time_zone(make_uow):
    # 23:30 UTC on 31 October is 00:30 on 1 November in Madrid (UTC+1 after the clock change).
    late = await bought(make_uow, datetime(2026, 10, 31, 23, 30, tzinfo=UTC))
    kept = await bought(make_uow, datetime(2026, 10, 31, 22, 30, tzinfo=UTC))

    async with make_uow() as uow:
        october_page = await uow.receipts.history(1, 2026, 10, MADRID)
        november_page = await uow.receipts.history(1, 2026, 11, MADRID)
        utc_page = await uow.receipts.history(1, 2026, 10, "UTC")

    assert [(r.receipt_id, r.day) for r in october_page.rows] == [(kept.id, date(2026, 10, 31))]
    assert [(r.receipt_id, r.day) for r in november_page.rows] == [(late.id, date(2026, 11, 1))]
    assert {r.receipt_id for r in utc_page.rows} == {late.id, kept.id}


async def test_a_row_carries_the_store_the_amount_the_currency_and_the_status(make_uow):
    one = await bought(make_uow, at(10), store="lidl", total="23.10", currency="USD")

    (row,) = (await october(make_uow)).rows

    assert row == HistoryRow(
        receipt_id=one.id,
        day=date(2026, 10, 10),
        store_name="Lidl",
        total=Decimal("23.10"),
        currency="USD",
        status="parsed",
    )


async def test_deleted_receipts_are_left_out_of_rows_counts_totals_and_stores(make_uow):
    kept = await bought(make_uow, at(10), store="lidl", total="5.00")
    await bought(make_uow, at(11), store="aldi", total="7.00", deleted=True)
    await bought(make_uow, at(12, month=9), deleted=True)
    await bought(make_uow, at(12, month=11), deleted=True)

    page = await october(make_uow)

    assert [r.receipt_id for r in page.rows] == [kept.id]
    assert (page.total_rows, page.parsed_count) == (1, 1)
    assert page.totals == [CurrencyTotal(currency="EUR", amount=Decimal("5.00"))]
    assert [s.name for s in page.stores] == ["Lidl"]
    assert (page.has_earlier, page.has_later) == (False, False)


async def test_rows_are_newest_first_with_the_id_breaking_ties(make_uow):
    old = await bought(make_uow, at(3))
    same_first = await bought(make_uow, at(9))
    same_second = await bought(make_uow, at(9))
    unread = await failed(make_uow, at(20))

    page = await october(make_uow)

    assert [r.receipt_id for r in page.rows] == [
        unread.id,
        same_second.id,
        same_first.id,
        old.id,
    ]


async def test_offset_and_limit_page_the_rows_and_total_rows_counts_them_all(make_uow):
    made = [await bought(make_uow, at(day)) for day in range(1, 6)]
    newest_first = [r.id for r in reversed(made)]

    async with make_uow() as uow:
        first = await uow.receipts.history(1, 2026, 10, MADRID, offset=0, limit=2)
        last = await uow.receipts.history(1, 2026, 10, MADRID, offset=4, limit=2)
        past = await uow.receipts.history(1, 2026, 10, MADRID, offset=10, limit=2)

    assert [r.receipt_id for r in first.rows] == newest_first[:2]
    assert [r.receipt_id for r in last.rows] == newest_first[4:]
    assert (past.rows, past.total_rows, past.parsed_count) == ([], 5, 5)
    assert first.total_rows == last.total_rows == 5


async def test_only_parsed_receipts_are_counted_and_summed_one_entry_per_currency(make_uow):
    await bought(make_uow, at(1), total="10.00")
    await bought(make_uow, at(2), total="5.50")
    await bought(make_uow, at(3), total="8.00", currency="USD")
    original = await bought(make_uow, at(4, month=9))
    await bought(make_uow, at(4), total="99.00", duplicate_of=original.id)
    await failed(make_uow, at(5))

    page = await october(make_uow)

    assert page.total_rows == 5
    assert page.parsed_count == 3
    assert page.totals == [
        CurrencyTotal(currency="EUR", amount=Decimal("15.50")),
        CurrencyTotal(currency="USD", amount=Decimal("8.00")),
    ]
    assert {r.status for r in page.rows} == {"parsed", "duplicate", "failed"}


async def test_the_store_filter_narrows_rows_counts_and_totals_but_not_the_stores(make_uow):
    await bought(make_uow, at(1), store="lidl", total="10.00")
    await bought(make_uow, at(2), store="lidl", total="2.00")
    await bought(make_uow, at(3), store="aldi", total="7.00")
    await failed(make_uow, at(4))
    lidl = await store_id_of(make_uow, "lidl")

    page = await october(make_uow, store_id=lidl)

    assert {r.store_name for r in page.rows} == {"Lidl"}
    assert (page.total_rows, page.parsed_count) == (2, 2)
    assert page.totals == [CurrencyTotal(currency="EUR", amount=Decimal("12.00"))]
    assert page.store_name == "Lidl"
    assert [s.name for s in page.stores] == ["Aldi", "Lidl"]
    assert page.stores[1].store_id == lidl


async def test_the_stores_are_those_with_a_receipt_in_the_month(make_uow):
    await bought(make_uow, at(1), store="lidl")
    await bought(make_uow, at(2), store="lidl")
    await bought(make_uow, at(3, month=9), store="aldi")

    page = await october(make_uow)

    assert [s.name for s in page.stores] == ["Lidl"]
    assert (await october(make_uow, store_id=None)).store_name is None


async def test_a_store_that_is_not_the_users_matches_nothing(make_uow):
    await bought(make_uow, at(1))

    page = await october(make_uow, store_id=987654)

    assert (page.rows, page.total_rows, page.parsed_count, page.totals) == ([], 0, 0, [])
    assert page.store_name is None
    assert len(page.stores) == 1


async def test_has_earlier_and_has_later_look_for_any_receipt_outside_the_month(make_uow):
    await bought(make_uow, at(10))

    assert (await october(make_uow)).has_earlier is False
    assert (await october(make_uow)).has_later is False

    await bought(make_uow, at(20, month=8))
    await failed(make_uow, at(2, month=12))

    page = await october(make_uow)
    assert (page.has_earlier, page.has_later) == (True, True)
    async with make_uow() as uow:
        august = await uow.receipts.history(1, 2026, 8, MADRID)
        december = await uow.receipts.history(1, 2026, 12, MADRID)
    assert (august.has_earlier, august.has_later) == (False, True)
    assert (december.has_earlier, december.has_later) == (True, False)


async def test_another_users_receipts_are_never_shown(make_uow):
    await bought(make_uow, at(10))
    await add_user(make_uow, 2)

    async with make_uow() as uow:
        page = await uow.receipts.history(2, 2026, 10, MADRID)

    assert (page.rows, page.total_rows, page.stores) == ([], 0, [])
    assert (page.has_earlier, page.has_later) == (False, False)


async def test_an_empty_month_is_an_empty_page(make_uow):
    await add_user(make_uow)

    page = await october(make_uow)

    assert page == HistoryPage(
        year=2026,
        month=10,
        rows=[],
        total_rows=0,
        parsed_count=0,
        totals=[],
        stores=[],
        has_earlier=False,
        has_later=False,
        store_name=None,
    )


@pytest.mark.parametrize("size", [3, 30])
async def test_history_runs_the_same_statements_whatever_the_month_size(make_uow, statements, size):
    for n in range(size):
        await bought(make_uow, at(1 + n % 28), store=f"shop{n % 4}")
    lidl = await store_id_of(make_uow, "shop1")
    statements.clear()

    await october(make_uow, store_id=lidl, limit=8)

    assert len([s for s in statements if s.startswith("SELECT")]) == HISTORY_STATEMENTS


# --- re-parse candidates -----------------------------------------------------------------


async def read(
    make_uow: MakeUow,
    version: str,
    *,
    user_id: int = 1,
    not_receipt: bool = False,
    deleted: bool = False,
) -> Receipt:
    n = next(_history_ids)
    await add_user(make_uow, user_id)
    receipt = Receipt.start(user_id, photo(f"c{n}"))
    if not_receipt:
        receipt.apply_parse(parse(is_receipt=False, parser_version=version))
    else:
        one = parse(
            product(f"mercadona::c{n}"), parser_version=version, receipt_key=f"mercadona|c{n}"
        )
        await seed_catalog(make_uow, one, user_id=user_id)
        receipt.apply_parse(one)
    if deleted:
        receipt.soft_delete()
    return await persist(make_uow, receipt)


async def failed_read(make_uow: MakeUow, *, user_id: int = 1, deleted: bool = False) -> Receipt:
    n = next(_history_ids)
    await add_user(make_uow, user_id)
    receipt = Receipt.start(user_id, photo(f"c{n}"))
    receipt.mark_failed("down")
    if deleted:
        receipt.soft_delete()
    return await persist(make_uow, receipt)


async def candidates(make_uow: MakeUow, version: str = "v2", user_id: int = 1):
    async with make_uow() as uow:
        return await uow.receipts.reparse_candidates(user_id, version)


async def test_failed_candidates_are_the_users_failed_receipts_oldest_first(make_uow):
    first = await failed_read(make_uow)
    await read(make_uow, "v2")
    second = await failed_read(make_uow)
    await failed_read(make_uow, deleted=True)
    await failed_read(make_uow, user_id=2)

    found = await candidates(make_uow)

    assert found.failed_ids == [first.id, second.id]
    assert found.outdated_ids == []


async def test_outdated_candidates_are_parsed_and_not_receipts_of_another_version(make_uow):
    old = await read(make_uow, "v1")
    await read(make_uow, "v2")
    old_not_receipt = await read(make_uow, "v1", not_receipt=True)
    await read(make_uow, "v1", deleted=True)
    await read(make_uow, "v1", user_id=2)
    duplicate = await read(make_uow, "v1")
    async with make_uow() as uow:
        receipt = await uow.receipts.get(duplicate.id)
        receipt.mark_duplicate(old.id)
        await uow.receipts.save(receipt)
        await uow.commit()

    found = await candidates(make_uow)

    assert found.outdated_ids == [old.id, old_not_receipt.id]
    assert found.failed_ids == []


async def test_a_reparsed_receipt_is_no_longer_outdated(make_uow):
    old = await read(make_uow, "v1")
    async with make_uow() as uow:
        receipt = await uow.receipts.get(old.id)
        receipt.apply_parse(replace(receipt.parse, parser_version="v2"))
        await uow.receipts.save(receipt)
        await uow.commit()

    assert (await candidates(make_uow)).outdated_ids == []


async def test_parsing_ids_are_every_users_parsing_receipts_oldest_first(make_uow):
    await add_user(make_uow, 1)
    await add_user(make_uow, 2)
    ids = []
    for user_id, parsing in ((1, True), (2, True), (1, False), (2, True)):
        receipt = Receipt.start(user_id, photo(f"p{next(_history_ids)}"))
        if parsing:
            receipt.mark_parsing()
        ids.append((await persist(make_uow, receipt)).id)

    async with make_uow() as uow:
        found = await uow.receipts.parsing_ids()

    assert found == [ids[0], ids[1], ids[3]]


async def test_a_reparse_rewrites_the_issues_with_the_carried_resolutions(make_uow):
    doubt = ParsedIssue(issue_type="unclear", severity=IssueSeverity.MEDIUM, message="Check it")
    await add_user(make_uow)
    one = parse(product("mercadona::carry"), issues=(doubt,))
    await seed_catalog(make_uow, one)
    receipt = Receipt.start(1, photo("carry"))
    receipt.apply_parse(one)
    receipt = await persist(make_uow, receipt)
    async with make_uow() as uow:
        receipt = await uow.receipts.get(receipt.id)
        receipt.resolve_issue(receipt.issues[0].id, IssueResolution.SKIPPED, WHEN)
        await uow.receipts.save(receipt)
        await uow.commit()

    async with make_uow() as uow:
        receipt = await uow.receipts.get(receipt.id)
        receipt.mark_parsing()
        receipt.apply_parse(replace(one, parser_version="v2"))
        await uow.receipts.save(receipt)
        await uow.commit()

    stored = await load(make_uow, receipt.id)
    assert [(i.message, i.resolution, i.resolved_at) for i in stored.issues] == [
        ("Check it", IssueResolution.SKIPPED, WHEN)
    ]


# --- spending --------------------------------------------------------------------------------

D = Decimal


async def spent(
    make_uow: MakeUow,
    purchased_at: datetime,
    *lines: tuple[Category, str],
    store: str = "mercadona",
    total: str | None = None,
    currency: str = "EUR",
    card: tuple[str | None, str] | None = None,
    deleted: bool = False,
    duplicate_of: int | None = None,
    user_id: int = 1,
) -> Receipt:
    """A stored receipt of the user whose item lines are `(category, amount)`; the total is the
    lines' sum unless given."""
    n = next(_history_ids)
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
    receipt = Receipt.start(user_id, photo(f"s{user_id}-{n}"))
    receipt.apply_parse(one)
    if duplicate_of is not None:
        receipt.mark_duplicate(duplicate_of)
    if deleted:
        receipt.soft_delete()
    return await persist(make_uow, receipt)


async def october_spending(make_uow: MakeUow, *, user_id: int = 1, tz: str = MADRID):
    async with make_uow() as uow:
        return await uow.receipts.spending(user_id, date(2026, 10, 1), date(2026, 11, 1), tz)


def only_block(period: SpendingPeriod) -> CurrencyBlock:
    [block] = period.blocks
    return block


async def test_spending_membership_is_the_purchase_date_in_the_time_zone(make_uow):
    await spent(make_uow, at(10), (Category.DAIRY, "5.00"))
    # 23:30 UTC on the last day of October is already 00:30 on 1 November in Madrid.
    await spent(make_uow, at(31, 23), (Category.DAIRY, "7.00"), store="late")
    await spent(make_uow, datetime(2026, 10, 31, 23, 30, tzinfo=UTC), (Category.DAIRY, "9.00"))
    # 23:30 UTC on 30 September is 01:30 on 1 October in Madrid (CEST, UTC+2).
    await spent(
        make_uow, datetime(2026, 9, 30, 23, 30, tzinfo=UTC), (Category.PANTRY, "3.00"), store="e"
    )
    await spent(make_uow, at(10, month=9), (Category.DAIRY, "100.00"))

    block = only_block(await october_spending(make_uow))
    assert (block.total, block.receipt_count) == (D("8.00"), 2)
    assert [(a.key, a.value) for a in block.categories] == [
        ("dairy", D("5.00")),
        ("pantry", D("3.00")),
    ]

    async with make_uow() as uow:
        utc = await uow.receipts.spending(1, date(2026, 10, 1), date(2026, 11, 1), "UTC")
    assert only_block(utc).total == D("5.00") + D("7.00") + D("9.00")


async def test_spending_counts_only_parsed_and_not_deleted_receipts(make_uow):
    await spent(make_uow, at(2), (Category.DAIRY, "5.00"))
    await spent(make_uow, at(3), (Category.DAIRY, "50.00"), deleted=True)
    first = await spent(make_uow, at(4), (Category.DAIRY, "60.00"), store="dup")
    assert first.id is not None
    await spent(make_uow, at(5), (Category.DAIRY, "70.00"), duplicate_of=first.id)
    await failed(make_uow, at(6))

    block = only_block(await october_spending(make_uow))

    assert (block.total, block.receipt_count) == (D("65.00"), 2)


async def test_spending_has_one_block_per_currency_ordered_by_code(make_uow):
    await spent(make_uow, at(2), (Category.DAIRY, "5.00"))
    await spent(make_uow, at(3), (Category.MEAT, "40.00"), currency="USD", store="us")
    await spent(make_uow, at(4), (Category.DAIRY, "6.00"))

    period = await october_spending(make_uow)

    assert [(b.currency, b.total, b.receipt_count) for b in period.blocks] == [
        ("EUR", D("11.00"), 2),
        ("USD", D("40.00"), 1),
    ]
    assert [a.key for a in period.blocks[1].categories] == ["meat"]
    assert (period.start, period.end) == (date(2026, 10, 1), date(2026, 11, 1))


async def test_spending_categories_come_from_item_lines_largest_first_and_not_itemised_is_the_rest(
    make_uow,
):
    await spent(make_uow, at(2), (Category.DAIRY, "5.00"), (Category.MEAT, "12.50"))
    await spent(make_uow, at(3), (Category.DAIRY, "4.00"), (Category.PANTRY, "0.00"), total="9.00")

    block = only_block(await october_spending(make_uow))

    assert [(a.key, a.value) for a in block.categories] == [
        ("meat", D("12.50")),
        ("dairy", D("9.00")),
    ]
    assert block.total == D("26.50")
    assert block.not_itemised == D("5.00")
    assert sum(a.value for a in block.categories) + block.not_itemised == block.total


async def test_spending_categories_follow_the_catalog_at_query_time(make_uow):
    await spent(make_uow, at(2), (Category.DAIRY, "5.00"))
    async with make_uow() as uow:
        catalog = await uow.catalog.get(1)
        [key] = catalog.products
        catalog.set_category(key, Category.PET)
        await uow.catalog.save(catalog)
        await uow.commit()

    block = only_block(await october_spending(make_uow))

    assert [a.key for a in block.categories] == ["pet"]


async def test_spending_stores_are_summed_from_receipt_totals_largest_first(make_uow):
    await spent(make_uow, at(2), (Category.DAIRY, "5.00"), store="consum")
    await spent(make_uow, at(3), (Category.DAIRY, "4.00"), total="30.00", store="mercadona")
    await spent(make_uow, at(4), (Category.DAIRY, "4.00"), store="consum")

    block = only_block(await october_spending(make_uow))

    assert [(a.label, a.value) for a in block.stores] == [
        ("Mercadona", D("30.00")),
        ("Consum", D("9.00")),
    ]
    assert len({a.key for a in block.stores}) == 2


async def test_spending_cards_are_labelled_and_a_receipt_without_a_card_is_cash(make_uow):
    await spent(make_uow, at(2), (Category.DAIRY, "5.00"), card=("VISA", "0848"))
    await spent(make_uow, at(3), (Category.DAIRY, "6.00"), card=("VISA", "0848"))
    await spent(make_uow, at(4), (Category.DAIRY, "20.00"), card=(None, "1111"))
    await spent(make_uow, at(5), (Category.DAIRY, "1.00"))

    block = only_block(await october_spending(make_uow))

    assert block.cards == [
        Amount(key="1111", label="•1111", value=D("20.00")),
        Amount(key="0848", label="VISA •0848", value=D("11.00")),
        Amount(key="cash", label="", value=D("1.00")),
    ]


async def test_spending_ignores_another_users_receipts(make_uow):
    await spent(make_uow, at(2), (Category.DAIRY, "5.00"))
    await spent(make_uow, at(3), (Category.DAIRY, "99.00"), user_id=2)

    assert only_block(await october_spending(make_uow)).total == D("5.00")
    assert only_block(await october_spending(make_uow, user_id=2)).total == D("99.00")


async def test_an_empty_period_has_no_blocks(make_uow):
    await add_user(make_uow)

    period = await october_spending(make_uow)

    assert period == SpendingPeriod(start=date(2026, 10, 1), end=date(2026, 11, 1), blocks=[])


async def test_a_week_period_uses_the_same_bounds_rule(make_uow):
    await spent(make_uow, at(12, 7), (Category.DAIRY, "5.00"))  # Monday 09:00 Madrid
    await spent(make_uow, at(18, 21), (Category.DAIRY, "6.00"))  # Sunday 23:00 Madrid
    await spent(make_uow, at(18, 22), (Category.DAIRY, "7.00"))  # Monday 00:00 Madrid
    await spent(make_uow, at(11, 21), (Category.DAIRY, "8.00"))  # Saturday 23:00 Madrid

    async with make_uow() as uow:
        week = await uow.receipts.spending(1, date(2026, 10, 12), date(2026, 10, 19), MADRID)

    assert only_block(week).total == D("11.00")


@pytest.mark.parametrize("size", [3, 30])
async def test_spending_runs_the_same_statements_whatever_the_size(make_uow, statements, size):
    for n in range(size):
        await spent(
            make_uow,
            at(1 + n % 28),
            (Category.DAIRY, "2.00"),
            (Category.MEAT, "3.00"),
            store=f"shop{n % 4}",
            card=("VISA", f"000{n % 3}") if n % 2 else None,
            currency="EUR" if n % 5 else "USD",
        )
    statements.clear()

    await october_spending(make_uow)

    assert len([s for s in statements if s.startswith("SELECT")]) == SPENDING_STATEMENTS


async def test_the_earliest_purchase_is_a_local_date_of_a_parsed_not_deleted_receipt(make_uow):
    await add_user(make_uow)
    async with make_uow() as uow:
        assert await uow.receipts.earliest_purchase(1, MADRID) is None
    await spent(make_uow, at(10, month=3), (Category.DAIRY, "5.00"), deleted=True)
    await failed(make_uow, at(1, month=1))
    await spent(make_uow, datetime(2026, 5, 31, 23, 30, tzinfo=UTC), (Category.DAIRY, "5.00"))
    await spent(make_uow, at(9), (Category.DAIRY, "5.00"))
    await spent(make_uow, at(1, month=1), (Category.DAIRY, "5.00"), user_id=2)

    async with make_uow() as uow:
        assert await uow.receipts.earliest_purchase(1, MADRID) == date(2026, 6, 1)
        assert await uow.receipts.earliest_purchase(1, "UTC") == date(2026, 5, 31)
