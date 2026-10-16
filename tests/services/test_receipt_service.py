"""ReceiptService through the Unit of Work on real Postgres. No LLM: parses are seeded by hand."""

from decimal import Decimal

import pytest
from sqlalchemy import text

from src.domain.enums import IssueResolution, ReceiptStatus
from src.domain.receipt import Receipt
from src.exception import DuplicatePhoto, InvalidReceiptTransition, ReceiptNotFound
from src.services.receipt import ReceiptService
from src.services.results import NewPhoto
from tests.domain.builders import WHEN, parse, photo, product
from tests.helpers import MakeUow, add_allowed_user, add_receipt, seed_catalog

MILK = product("mercadona::leche", total="1.20")
BREAD = product("mercadona::pan", total="2.00")


def new_photo(unique_id: str = "u1", **fields) -> NewPhoto:
    return NewPhoto(
        path=f"2026/10/{unique_id}.jpg",
        received_at=WHEN,
        telegram_file_unique_id=unique_id,
        **fields,
    )


async def seeded_receipt(make_uow: MakeUow, *parses, user_id: int = 1) -> Receipt:
    """A receipt with these parses applied in order (the last is current), catalog seeded."""
    await seed_catalog(make_uow, *parses, user_id=user_id)
    receipt = Receipt.start(user_id, photo(f"seed{user_id}"))
    for p in parses:
        receipt.apply_parse(p)
    return await add_receipt(make_uow, receipt)


async def load(make_uow: MakeUow, receipt_id: int) -> Receipt:
    async with make_uow() as uow:
        receipt = await uow.receipts.get(receipt_id)
    assert receipt is not None
    return receipt


@pytest.fixture
async def service(make_uow: MakeUow) -> ReceiptService:
    await add_allowed_user(make_uow, 1)
    return ReceiptService(make_uow)


async def test_save_photo_starts_a_pending_receipt(service):
    card = await service.save_photo(1, new_photo())

    assert (card.status, card.photo_count, card.item_count) == ("pending", 1, 0)
    assert card.store_name is None


async def test_save_photo_as_a_reply_attaches_to_the_remembered_receipt(service):
    first = await service.save_photo(1, new_photo("u1"))
    await service.remember_message(1, first.receipt_id, 500)

    second = await service.save_photo(1, new_photo("u2"), reply_to_message_id=500)

    assert second.receipt_id == first.receipt_id
    assert second.photo_count == 2


async def test_save_photo_as_a_reply_to_an_unknown_message_starts_a_receipt(service):
    first = await service.save_photo(1, new_photo("u1"))

    second = await service.save_photo(1, new_photo("u2"), reply_to_message_id=999)

    assert second.receipt_id != first.receipt_id


async def test_the_same_telegram_photo_twice_is_rejected_with_no_new_rows(service, connection):
    await service.save_photo(1, new_photo("u1"))
    with pytest.raises(DuplicatePhoto):
        await service.save_photo(1, new_photo("u1"))

    assert await connection.scalar(text("select count(*) from receipts")) == 1
    assert await connection.scalar(text("select count(*) from receipt_photos")) == 1


async def test_the_duplicate_check_applies_to_a_reply_too(service):
    first = await service.save_photo(1, new_photo("u1"))
    await service.remember_message(1, first.receipt_id, 500)

    with pytest.raises(DuplicatePhoto):
        await service.save_photo(1, new_photo("u1"), reply_to_message_id=500)


async def test_attach_photo_adds_a_photo_to_the_receipt(service):
    first = await service.save_photo(1, new_photo("u1"))

    card = await service.attach_photo(1, first.receipt_id, new_photo("u2"))

    assert card.photo_count == 2


async def test_undo_returns_the_card_of_the_earlier_parse(service, make_uow):
    first = parse(MILK, total=None, store_name="Mercadona")
    second = parse(MILK, BREAD, total=None)
    receipt = await seeded_receipt(make_uow, first, second)
    assert (await service.card(1, receipt.id)).item_count == 2
    first_id = (await load(make_uow, receipt.id)).parses[0].id
    assert first_id is not None

    card = await service.undo(1, receipt.id, first_id)

    assert card.item_count == 1
    assert (await service.card(1, receipt.id)).item_count == 1


async def test_undo_keeps_catalog_products_it_did_not_create(service, make_uow):
    receipt = await seeded_receipt(make_uow, parse(MILK), parse(MILK, BREAD, receipt_key="k2"))
    first_id = (await load(make_uow, receipt.id)).parses[0].id

    await service.undo(1, receipt.id, first_id)

    async with make_uow() as uow:
        assert {"mercadona::leche", "mercadona::pan"} <= set((await uow.catalog.get(1)).products)


async def test_edit_item_returns_the_updated_card_and_survives(service, make_uow):
    receipt = await seeded_receipt(make_uow, parse(MILK, total="1.20"))

    card = await service.edit_item(1, receipt.id, "mercadona::leche#1", "line_total", "1.50")

    assert card.receipt_id == receipt.id
    stored = await load(make_uow, receipt.id)
    assert stored.items[0].line_total == Decimal("1.50")
    assert [e.field for e in stored.edits] == ["line_total"]


async def test_edit_header_changes_the_card(service, make_uow):
    receipt = await seeded_receipt(make_uow, parse(MILK))

    card = await service.edit_header(1, receipt.id, "total", "9.99")

    assert str(card.total) == "9.99"


async def test_card_shows_store_name_payment_and_counts(service, make_uow):
    receipt = await seeded_receipt(
        make_uow, parse(MILK, BREAD, payment_method="card", card_brand="VISA", card_last4="1234")
    )

    card = await service.card(1, receipt.id)

    assert card.store_name == "Mercadona"
    assert (card.currency, str(card.total)) == ("EUR", "47.50")
    assert (card.payment_method, card.card_brand, card.card_last4) == ("card", "VISA", "1234")
    assert (card.item_count, card.photo_count, card.status) == (2, 1, "parsed")


async def test_resolve_issue_lowers_the_open_issue_count(service, make_uow):
    from src.domain.parse import ParsedIssue

    receipt = await seeded_receipt(make_uow, parse(MILK, issues=(ParsedIssue(message="odd"),)))
    assert (await service.card(1, receipt.id)).open_issue_count == 1
    issue_id = (await load(make_uow, receipt.id)).issues[0].id

    card = await service.resolve_issue(1, receipt.id, issue_id, IssueResolution.CONFIRMED)

    assert card.open_issue_count == 0


async def test_merge_marks_the_source_merged_and_gives_the_target_both_photos(service, make_uow):
    target = await seeded_receipt(make_uow, parse(MILK))
    await add_allowed_user(make_uow, 1)
    source = Receipt.start(1, photo("other"))
    source.apply_parse(parse(MILK, BREAD, receipt_key="other-key"))
    await seed_catalog(make_uow, parse(MILK, BREAD))
    source = await add_receipt(make_uow, source)

    card = await service.merge(1, source.id, target.id)

    assert card.receipt_id == target.id
    assert card.photo_count == 2
    assert card.item_count == 2
    merged = await load(make_uow, source.id)
    assert (merged.status, merged.merged_into_id) == (ReceiptStatus.MERGED, target.id)
    assert len((await load(make_uow, target.id)).photos) == 2


async def test_merge_of_a_receipt_without_a_parse_only_moves_the_photo(service):
    target = await service.save_photo(1, new_photo("u1"))
    source = await service.save_photo(1, new_photo("u2"))

    card = await service.merge(1, source.receipt_id, target.receipt_id)

    assert (card.photo_count, card.status) == (2, "pending")


async def test_merging_a_receipt_into_itself_is_refused(service):
    card = await service.save_photo(1, new_photo("u1"))

    with pytest.raises(InvalidReceiptTransition):
        await service.merge(1, card.receipt_id, card.receipt_id)


async def test_soft_delete_hides_the_receipt_from_find_by_key(service, make_uow):
    receipt = await seeded_receipt(make_uow, parse(MILK))
    key = "mercadona|0042|2026-10-14|47.50"
    async with make_uow() as uow:
        assert await uow.receipts.find_by_key(1, key) is not None

    await service.soft_delete(1, receipt.id)

    async with make_uow() as uow:
        assert await uow.receipts.find_by_key(1, key) is None


async def test_another_users_receipt_is_not_found(service, make_uow):
    await add_allowed_user(make_uow, 2)
    mine = await service.save_photo(1, new_photo("u1"))

    for call in (
        service.card(2, mine.receipt_id),
        service.attach_photo(2, mine.receipt_id, new_photo("u9")),
        service.soft_delete(2, mine.receipt_id),
        service.remember_message(2, mine.receipt_id, 5),
    ):
        with pytest.raises(ReceiptNotFound):
            await call


async def test_a_missing_receipt_is_not_found(service):
    with pytest.raises(ReceiptNotFound):
        await service.card(1, 12345)


async def test_undo_removes_a_product_only_the_undone_parse_introduced(
    service, make_uow, connection
):
    receipt = await seeded_receipt(make_uow, parse(MILK), parse(MILK, BREAD, receipt_key="k2"))
    await connection.execute(
        text("update store_products set created_by_receipt_id = :r where product_key = :k"),
        {"r": receipt.id, "k": "mercadona::pan"},
    )
    first_id = (await load(make_uow, receipt.id)).parses[0].id

    await service.undo(1, receipt.id, first_id)

    async with make_uow() as uow:
        products = set((await uow.catalog.get(1)).products)
    assert products == {"mercadona::leche"}


async def test_undo_keeps_a_product_another_receipt_also_uses(service, make_uow, connection):
    receipt = await seeded_receipt(make_uow, parse(MILK), parse(MILK, BREAD, receipt_key="k2"))
    await connection.execute(
        text("update store_products set created_by_receipt_id = :r where product_key = :k"),
        {"r": receipt.id, "k": "mercadona::pan"},
    )
    other = Receipt.start(1, photo("other"))
    other.apply_parse(parse(BREAD, receipt_key="k3"))
    await add_receipt(make_uow, other)
    first_id = (await load(make_uow, receipt.id)).parses[0].id

    await service.undo(1, receipt.id, first_id)

    async with make_uow() as uow:
        assert "mercadona::pan" in (await uow.catalog.get(1)).products
