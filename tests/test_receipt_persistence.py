"""Schema constraints of stores and products, proven through the Unit of Work.

Receipt constraints are tested through `ReceiptRepository` in `tests/database/`. These cases
move to the catalog repository when it replaces the per-table store repositories.
"""

import pytest

from src.database.dto.store import NewStoreDTO, NewStoreProductDTO
from src.domain.receipt import Receipt
from src.exception import CheckViolationError, ForeignKeyViolationError
from tests.domain.builders import parse, photo, product
from tests.helpers import MakeUow, add_receipt, add_user, seed_catalog


async def test_stores_and_products_round_trip_as_dtos(make_uow):
    await add_user(make_uow)
    async with make_uow() as uow:
        store = await uow.stores.add(NewStoreDTO(user_id=1, store_key="lidl", name="Lidl"))
        added = await uow.products.add(
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
        assert await uow.products.get(added.id) == added
    assert (store.store_key, store.name) == ("lidl", "Lidl")
    assert (added.category, added.unit) == ("other", "pcs")


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


async def seed_purchase(make_uow: MakeUow) -> tuple[int, int]:
    """A user with a store, a product and a receipt whose only item uses the product."""
    await add_user(make_uow)
    bought = parse(product("lidl::pan"), store_key="lidl", store_name="Lidl")
    stores, products = await seed_catalog(make_uow, bought)
    receipt = Receipt.start(1, photo())
    receipt.apply_parse(bought)
    await add_receipt(make_uow, receipt)
    return stores["lidl"], products["lidl::pan"]


async def test_product_used_by_an_item_cannot_be_deleted(make_uow):
    _, product_id = await seed_purchase(make_uow)
    async with make_uow() as uow:
        with pytest.raises(ForeignKeyViolationError):
            await uow.products.delete(product_id)


async def test_deleting_a_user_removes_stores_and_products(make_uow):
    store_id, product_id = await seed_purchase(make_uow)
    async with make_uow() as uow:
        await uow.users.delete(1)
        await uow.commit()

    async with make_uow() as uow:
        assert await uow.stores.get(store_id) is None
        assert await uow.products.get(product_id) is None
