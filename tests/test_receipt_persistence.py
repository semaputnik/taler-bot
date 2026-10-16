"""Schema constraints of stores, products, receipts and items, proven through the Unit of Work."""

from typing import Any

import pytest

from src.database.dto.receipt import NewReceiptDTO, NewReceiptItemDTO
from src.database.dto.store import NewStoreDTO, NewStoreProductDTO
from src.domain.enums import ReceiptStatus
from src.exception import (
    CheckViolationError,
    DataViolationError,
    ForeignKeyViolationError,
    UniqueViolationError,
)
from tests.helpers import NOW, MakeUow, add_receipt, add_user

KEY = "mercadona|A-123|2026-10-14|47.85"


async def test_stores_and_products_round_trip_as_dtos(make_uow):
    await add_user(make_uow)
    async with make_uow() as uow:
        store = await uow.stores.add(NewStoreDTO(user_id=1, store_key="lidl", name="Lidl"))
        product = await uow.products.add(
            NewStoreProductDTO(
                user_id=1,
                store_id=store.id,
                product_key="lidl::pan",
                name="Pan",
                name_raw="PAN",
            )
        )
        await uow.commit()

    async with make_uow() as uow:
        assert await uow.stores.get(store.id) == store
        assert await uow.products.get(product.id) == product
    assert (store.store_key, store.name) == ("lidl", "Lidl")
    assert (product.category, product.unit) == ("other", "pcs")


async def seed_purchase(make_uow: MakeUow, **receipt_fields: Any):
    """A user with a store, a product and a receipt whose only item uses the product."""
    await add_user(make_uow)
    async with make_uow() as uow:
        store = await uow.stores.add(NewStoreDTO(user_id=1, store_key="lidl", name="Lidl"))
        product = await uow.products.add(
            NewStoreProductDTO(
                user_id=1, store_id=store.id, product_key="lidl::pan", name="Pan", name_raw="PAN"
            )
        )
        receipt = await uow.receipts.add(
            NewReceiptDTO(user_id=1, store_id=store.id, **receipt_fields)
        )
        item = await uow.items.add(
            NewReceiptItemDTO(
                receipt_id=receipt.id,
                store_product_id=product.id,
                position=0,
                name_raw="PAN",
                quantity=1,
                unit="pcs",
            )
        )
        await uow.commit()
    return store, product, receipt, item


async def test_receipts_and_items_round_trip_as_dtos(make_uow: MakeUow) -> None:
    store, _, receipt, item = await seed_purchase(
        make_uow, status=ReceiptStatus.PARSED, card_last4="1234"
    )

    async with make_uow() as uow:
        assert await uow.receipts.get(receipt.id) == receipt
        assert await uow.items.get(item.id) == item
    assert (receipt.status, receipt.card_last4, receipt.store_id) == ("parsed", "1234", store.id)
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


async def test_unknown_product_category_is_rejected(make_uow):
    await add_user(make_uow)
    async with make_uow() as uow:
        store = await uow.stores.add(NewStoreDTO(user_id=1, store_key="lidl", name="Lidl"))
        with pytest.raises(CheckViolationError):
            await uow.products.add(
                NewStoreProductDTO(
                    user_id=1,
                    store_id=store.id,
                    product_key="lidl::pan",
                    name="Pan",
                    name_raw="PAN",
                    category="bread",
                )
            )


async def test_product_used_by_an_item_cannot_be_deleted(make_uow):
    _, product, _, _ = await seed_purchase(make_uow)
    async with make_uow() as uow:
        with pytest.raises(ForeignKeyViolationError):
            await uow.products.delete(product.id)


async def test_deleting_a_user_removes_stores_products_receipts_and_items(make_uow):
    store, product, receipt, item = await seed_purchase(make_uow)
    async with make_uow() as uow:
        await uow.users.delete(1)
        await uow.commit()

    async with make_uow() as uow:
        assert await uow.stores.get(store.id) is None
        assert await uow.products.get(product.id) is None
        assert await uow.receipts.get(receipt.id) is None
        assert await uow.items.get(item.id) is None
