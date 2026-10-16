"""ReceiptService through the Unit of Work on real Postgres. No LLM: parses are seeded by hand."""

from decimal import Decimal

import pytest
from sqlalchemy import text

from src.domain.enums import IssueResolution
from src.domain.parse import Parse, ParsedIssue
from src.domain.receipt import Receipt
from src.exception import DuplicatePhoto, ReceiptNotFound
from src.services.receipt import ReceiptService, _apply_parse
from src.services.results import NewPhoto
from tests.domain.builders import WHEN, parse, photo, product
from tests.helpers import MakeUow, add_allowed_user, add_receipt, seed_catalog

MILK = product("mercadona::leche", total="1.20")
BREAD = product("mercadona::pan", total="2.00")
KEY = "mercadona|0042|2026-10-14|47.50"


def new_photo(unique_id: str = "u1", **fields) -> NewPhoto:
    return NewPhoto(
        path=f"2026/10/{unique_id}.jpg",
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
async def service(make_uow: MakeUow) -> ReceiptService:
    await add_allowed_user(make_uow, 1)
    return ReceiptService(make_uow)


async def test_save_photo_starts_a_pending_receipt(service):
    card = await service.save_photo(1, new_photo())

    assert (card.status, card.item_count, card.open_issue_count) == ("pending", 0, 0)
    assert card.store_name is None


async def test_the_same_telegram_photo_twice_is_rejected_with_no_new_rows(service, connection):
    await service.save_photo(1, new_photo("u1"))
    with pytest.raises(DuplicatePhoto):
        await service.save_photo(1, new_photo("u1"))

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
    mine = await service.save_photo(1, new_photo("u1"))

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
