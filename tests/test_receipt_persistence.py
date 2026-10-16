"""Schema constraints of stores, products, receipts and items, proven through the Unit of Work."""

import pytest

from src.domain.enums import ReceiptStatus
from src.exception import (
    CheckViolationError,
    DataViolationError,
    UniqueViolationError,
)
from tests.helpers import NOW, MakeUow, add_receipt, add_user, seed_purchase

KEY = "mercadona|A-123|2026-10-14|47.85"


async def test_receipts_and_items_round_trip_as_dtos(make_uow: MakeUow) -> None:
    store, _, receipt, item_id = await seed_purchase(
        make_uow, status=ReceiptStatus.PARSED, card_last4="1234"
    )

    async with make_uow() as uow:
        assert await uow.receipts.get(receipt.id) == receipt
        item = await uow.items.get(item_id)
    assert (receipt.status, receipt.card_last4, receipt.store_id) == ("parsed", "1234", store.id)
    assert item is not None
    assert (item.quantity, item.discount) == (1, 0)


async def test_parsed_receipt_key_is_unique_per_user(make_uow):
    await add_user(make_uow, 1)
    await add_user(make_uow, 2)
    await add_receipt(make_uow, status=ReceiptStatus.PARSED, receipt_key=KEY)

    await add_receipt(make_uow, user_id=2, status=ReceiptStatus.PARSED, receipt_key=KEY)
    await add_receipt(make_uow, status=ReceiptStatus.AWAITING_MATCH, receipt_key=KEY)
    await add_receipt(make_uow, status=ReceiptStatus.PARSED, receipt_key=KEY, deleted_at=NOW)
    with pytest.raises(UniqueViolationError):
        await add_receipt(make_uow, status=ReceiptStatus.PARSED, receipt_key=KEY)


@pytest.mark.parametrize("value", ["ab12", "12 3", "123"])
async def test_card_last4_is_exactly_four_digits(make_uow, value):
    await add_user(make_uow)
    with pytest.raises(CheckViolationError):
        await add_receipt(make_uow, card_last4=value)


async def test_card_last4_longer_than_four_characters_is_rejected(make_uow):
    await add_user(make_uow)
    with pytest.raises(DataViolationError):
        await add_receipt(make_uow, card_last4="12345")


async def test_merged_receipt_needs_a_target_and_only_merged_may_have_one(make_uow):
    await add_user(make_uow)
    target = await add_receipt(make_uow, status=ReceiptStatus.PARSED)

    merged = await add_receipt(make_uow, status=ReceiptStatus.MERGED, merged_into_id=target.id)
    assert merged.merged_into_id == target.id
    with pytest.raises(CheckViolationError):
        await add_receipt(make_uow, status=ReceiptStatus.MERGED)
    with pytest.raises(CheckViolationError):
        await add_receipt(make_uow, status=ReceiptStatus.PARSED, merged_into_id=target.id)


async def test_unknown_receipt_status_is_rejected(make_uow):
    await add_user(make_uow)
    with pytest.raises(CheckViolationError):
        await add_receipt(make_uow, status="duplicate")
