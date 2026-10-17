"""CatalogService through the Unit of Work on real Postgres."""

import pytest

from src.domain.enums import ProductCategory
from src.exception import InvalidEdit, UnknownProduct
from src.services.catalog import CatalogService
from src.services.results import ProductCard
from tests.domain.builders import parse, product
from tests.helpers import MakeUow, add_allowed_user, seed_catalog

MILK = product("mercadona::leche")


@pytest.fixture
async def service(make_uow: MakeUow) -> CatalogService:
    await add_allowed_user(make_uow, 1)
    await add_allowed_user(make_uow, 2, username="bob")
    await seed_catalog(make_uow, parse(MILK))
    return CatalogService(make_uow)


async def stored(make_uow: MakeUow, user_id: int = 1):
    async with make_uow() as uow:
        return (await uow.catalog.get(user_id)).products["mercadona::leche"]


async def test_rename_product_returns_the_card_and_persists(service, make_uow):
    card = await service.rename_product(1, "mercadona::leche", "  Oat milk ")

    assert card == ProductCard(
        product_key="mercadona::leche",
        store_key="mercadona",
        printed_name="LECHE",
        name="Oat milk",
        category="dairy",
    )
    assert (await stored(make_uow)).name == "Oat milk"


async def test_set_category_returns_the_card_and_persists(service, make_uow):
    card = await service.set_category(1, "mercadona::leche", "drinks")

    assert (card.category, card.name) == ("drinks", "Leche")
    assert (await stored(make_uow)).category is ProductCategory.DRINKS


async def test_an_unknown_category_is_refused_and_changes_nothing(service, make_uow):
    with pytest.raises(InvalidEdit):
        await service.set_category(1, "mercadona::leche", "bread")

    assert (await stored(make_uow)).category is ProductCategory.DAIRY


async def test_an_empty_name_is_refused(service, make_uow):
    with pytest.raises(InvalidEdit):
        await service.rename_product(1, "mercadona::leche", "  ")

    assert (await stored(make_uow)).name == "Leche"


async def test_another_users_catalog_has_no_such_product(service, make_uow):
    with pytest.raises(UnknownProduct):
        await service.rename_product(2, "mercadona::leche", "Mine")
    with pytest.raises(UnknownProduct):
        await service.set_category(2, "mercadona::leche", "drinks")

    assert (await stored(make_uow)).name == "Leche"
