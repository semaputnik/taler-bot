"""Schema constraints of stores, products, receipts and items, proven through the Unit of Work."""

from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.dto.receipt import NewReceiptDTO, NewReceiptItemDTO
from src.database.dto.store import NewStoreDTO, NewStoreProductDTO
from src.database.dto.user import NewUserDTO
from src.database.uow.sqlalchemy import SqlAlchemyUnitOfWork
from src.domain.enums import ReceiptStatus
from src.exception import CheckViolationError, ForeignKeyViolationError, UniqueViolationError

NOW = datetime(2026, 10, 14, 18, 32, tzinfo=UTC)
KEY = "mercadona|A-123|2026-10-14|47.85"


@pytest.fixture
def make_uow(session_factory: Callable[[], AsyncSession]) -> Callable[[], SqlAlchemyUnitOfWork]:
    return lambda: SqlAlchemyUnitOfWork(session_factory)


async def add_user(make_uow, user_id: int = 1) -> None:
    async with make_uow() as uow:
        await uow.users.upsert(NewUserDTO(id=user_id, username=None, first_name=None))
        await uow.commit()


async def add_receipt(make_uow, user_id: int = 1, **fields):
    """Add a receipt in its own Unit of Work: a rejected row poisons the transaction."""
    async with make_uow() as uow:
        receipt = await uow.receipts.add(NewReceiptDTO(user_id=user_id, **fields))
        await uow.commit()
    return receipt


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


async def test_receipts_and_items_round_trip_as_dtos(make_uow):
    await add_user(make_uow)
    async with make_uow() as uow:
        store = await uow.stores.add(NewStoreDTO(user_id=1, store_key="lidl", name="Lidl"))
        product = await uow.products.add(
            NewStoreProductDTO(
                user_id=1, store_id=store.id, product_key="lidl::pan", name="Pan", name_raw="PAN"
            )
        )
        receipt = await uow.receipts.add(
            NewReceiptDTO(
                user_id=1, store_id=store.id, status=ReceiptStatus.PARSED, card_last4="1234"
            )
        )
        item = await uow.items.add(
            NewReceiptItemDTO(
                receipt_id=receipt.id,
                store_product_id=product.id,
                position=0,
                name_raw="PAN",
                quantity=2,
                unit="pcs",
            )
        )
        await uow.commit()

    async with make_uow() as uow:
        assert await uow.receipts.get(receipt.id) == receipt
        assert await uow.items.get(item.id) == item
    assert (receipt.status, receipt.card_last4, receipt.store_id) == ("parsed", "1234", store.id)
    assert (item.quantity, item.discount) == (2, 0)


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


async def seed_purchase(make_uow):
    """A user with a store, a product and a receipt whose only item uses the product."""
    await add_user(make_uow)
    async with make_uow() as uow:
        store = await uow.stores.add(NewStoreDTO(user_id=1, store_key="lidl", name="Lidl"))
        product = await uow.products.add(
            NewStoreProductDTO(
                user_id=1, store_id=store.id, product_key="lidl::pan", name="Pan", name_raw="PAN"
            )
        )
        receipt = await uow.receipts.add(NewReceiptDTO(user_id=1, store_id=store.id))
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
