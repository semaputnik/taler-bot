"""`CatalogRepository` through the Unit of Work, on real Postgres."""

import pytest

from src.domain.catalog import Catalog
from src.domain.enums import Category
from src.exception import CheckViolationError, ForeignKeyViolationError
from tests.helpers import MakeUow, add_user, seed_purchase


def stocked_catalog() -> Catalog:
    catalog = Catalog(user_id=1)
    catalog.ensure_store("mercadona", "Mercadona", legal_name="Mercadona, S.A.", tax_id="A-1")
    catalog.ensure_store("lidl", "Lidl")
    catalog.ensure_product(
        "mercadona", "mercadona::leche", "LECHE ENTERA", "Whole milk", Category.DAIRY, "l"
    )
    catalog.ensure_product("lidl", "lidl::pan", "PAN", "Bread", Category.BAKERY, "pcs")
    return catalog


async def test_a_user_without_a_catalog_gets_an_empty_one(make_uow: MakeUow) -> None:
    await add_user(make_uow)
    async with make_uow() as uow:
        assert await uow.catalog.get(1) == Catalog(user_id=1)


async def test_a_saved_catalog_loads_equal(make_uow: MakeUow) -> None:
    await add_user(make_uow)
    async with make_uow() as uow:
        catalog = stocked_catalog()
        await uow.catalog.save(catalog)
        await uow.commit()

    async with make_uow() as uow:
        loaded = await uow.catalog.get(1)
    assert loaded == catalog  # ids were assigned to the saved aggregate
    assert all(store.id is not None for store in loaded.stores.values())
    assert all(product.id is not None for product in loaded.products.values())


async def test_save_inserts_only_what_is_new_and_leaves_the_rest_alone(make_uow: MakeUow) -> None:
    await add_user(make_uow)
    async with make_uow() as uow:
        await uow.catalog.save(stocked_catalog())
        await uow.commit()

    async with make_uow() as uow:
        catalog = await uow.catalog.get(1)
        catalog.ensure_product("lidl", "lidl::agua", "AGUA", "Water", Category.DRINKS, "l")
        catalog.products["lidl::pan"].name = "edited in memory only"
        await uow.catalog.save(catalog)
        await uow.commit()

    async with make_uow() as uow:
        loaded = await uow.catalog.get(1)
    assert set(loaded.products) == {"mercadona::leche", "lidl::pan", "lidl::agua"}
    assert loaded.products["lidl::pan"].name == "Bread"


async def test_save_deletes_products_marked_for_removal(make_uow: MakeUow) -> None:
    await add_user(make_uow)
    async with make_uow() as uow:
        await uow.catalog.save(stocked_catalog())
        await uow.commit()

    async with make_uow() as uow:
        catalog = await uow.catalog.get(1)
        catalog.remove_unreferenced({"lidl::pan"})
        await uow.catalog.save(catalog)
        assert catalog.removed_product_keys == frozenset()
        await uow.commit()

    async with make_uow() as uow:
        assert set((await uow.catalog.get(1)).products) == {"mercadona::leche"}


async def test_product_used_by_an_item_cannot_be_removed(make_uow: MakeUow) -> None:
    await seed_purchase(make_uow)
    async with make_uow() as uow:
        catalog = await uow.catalog.get(1)
        catalog.remove_unreferenced({"lidl::pan"})
        with pytest.raises(ForeignKeyViolationError):
            await uow.catalog.save(catalog)


async def test_unknown_product_category_is_rejected(make_uow: MakeUow) -> None:
    await add_user(make_uow)
    catalog = Catalog(user_id=1)
    catalog.ensure_store("lidl", "Lidl")
    catalog.ensure_product("lidl", "lidl::pan", "PAN", "Pan", "bread", "pcs")  # type: ignore[arg-type]
    async with make_uow() as uow:
        with pytest.raises(CheckViolationError):
            await uow.catalog.save(catalog)


async def test_catalogs_are_per_user(make_uow: MakeUow) -> None:
    await add_user(make_uow, 1)
    await add_user(make_uow, 2)
    async with make_uow() as uow:
        await uow.catalog.save(stocked_catalog())
        await uow.commit()

    async with make_uow() as uow:
        assert await uow.catalog.get(2) == Catalog(user_id=2)


async def test_deleting_a_user_removes_their_catalog(make_uow: MakeUow) -> None:
    await seed_purchase(make_uow)
    async with make_uow() as uow:
        await uow.users.delete(1)
        await uow.commit()

    async with make_uow() as uow:
        assert await uow.catalog.get(1) == Catalog(user_id=1)
