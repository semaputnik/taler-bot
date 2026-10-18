"""`CatalogRepository` through the Unit of Work, on real Postgres."""

import pytest

from src.domain.catalog import Catalog, PaymentSource
from src.domain.enums import PaymentSourceKind, ProductCategory
from src.domain.receipt import Receipt
from src.exception import CheckViolationError, ForeignKeyViolationError, UniqueViolationError
from tests.domain.builders import parse, photo, product
from tests.helpers import MakeUow, add_receipt, add_user, seed_catalog, seed_purchase


def stocked_catalog() -> Catalog:
    catalog = Catalog(user_id=1)
    catalog.ensure_payee("mercadona", "Mercadona", legal_name="Mercadona, S.A.", tax_id="A-1")
    catalog.ensure_payee("lidl", "Lidl")
    catalog.ensure_product(
        "mercadona", "mercadona::leche", "LECHE ENTERA", "Whole milk", ProductCategory.DAIRY, "l"
    )
    catalog.ensure_product("lidl", "lidl::pan", "PAN", "Bread", ProductCategory.BAKERY, "pcs")
    catalog.ensure_payee("landlord", "Landlord")  # a payee without products
    catalog.ensure_card("VISA", "0848")
    catalog.cash()
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
    assert all(payee.id is not None for payee in loaded.payees.values())
    assert all(source.id is not None for source in loaded.payment_sources.values())
    assert set(loaded.payment_sources) == {s.id for s in loaded.payment_sources.values()}
    assert all(product.id is not None for product in loaded.products.values())


async def test_save_inserts_only_what_is_new_and_leaves_the_rest_alone(make_uow: MakeUow) -> None:
    await add_user(make_uow)
    async with make_uow() as uow:
        await uow.catalog.save(stocked_catalog())
        await uow.commit()

    async with make_uow() as uow:
        catalog = await uow.catalog.get(1)
        catalog.ensure_product("lidl", "lidl::agua", "AGUA", "Water", ProductCategory.DRINKS, "l")
        catalog.products["lidl::pan"].name = "edited in memory only"
        await uow.catalog.save(catalog)
        await uow.commit()

    async with make_uow() as uow:
        loaded = await uow.catalog.get(1)
    assert set(loaded.products) == {"mercadona::leche", "lidl::pan", "lidl::agua"}
    assert loaded.products["lidl::pan"].name == "Bread"


async def test_save_persists_a_renamed_and_a_recategorized_product_and_nothing_else(
    make_uow: MakeUow,
) -> None:
    await add_user(make_uow)
    async with make_uow() as uow:
        await uow.catalog.save(stocked_catalog())
        await uow.commit()

    async with make_uow() as uow:
        catalog = await uow.catalog.get(1)
        catalog.rename_product("mercadona::leche", "Oat milk")
        catalog.set_category("mercadona::leche", ProductCategory.DRINKS)
        await uow.catalog.save(catalog)
        assert catalog.changed_products == ()
        await uow.commit()

    async with make_uow() as uow:
        loaded = await uow.catalog.get(1)
    milk = loaded.products["mercadona::leche"]
    assert (milk.name, milk.category) == ("Oat milk", ProductCategory.DRINKS)
    assert (milk.name_raw, milk.unit, milk.payee_key) == ("LECHE ENTERA", "l", "mercadona")
    bread = loaded.products["lidl::pan"]
    assert (bread.name, bread.category) == ("Bread", ProductCategory.BAKERY)


async def test_a_reloaded_receipt_shows_the_new_name_and_category_on_its_items(
    make_uow: MakeUow,
) -> None:
    await add_user(make_uow)
    bought = parse(product("lidl::pan"), store_key="lidl", store_name="Lidl")
    await seed_catalog(make_uow, bought)
    receipt = Receipt.start(1, photo())
    receipt.apply_parse(bought)
    receipt = await add_receipt(make_uow, receipt)
    async with make_uow() as uow:
        catalog = await uow.catalog.get(1)
        catalog.rename_product("lidl::pan", "Sourdough")
        catalog.set_category("lidl::pan", ProductCategory.BAKERY)
        await uow.catalog.save(catalog)
        await uow.commit()

    async with make_uow() as uow:
        loaded = await uow.receipts.get(receipt.id)
    assert loaded is not None
    [item] = loaded.items
    assert (item.readable_name, item.category) == ("Sourdough", ProductCategory.BAKERY)
    assert item.printed_name == "PAN"


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
    catalog.ensure_payee("lidl", "Lidl")
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


async def test_payees_without_products_and_payment_sources_round_trip(make_uow: MakeUow) -> None:
    await add_user(make_uow)
    async with make_uow() as uow:
        saved = stocked_catalog()
        await uow.catalog.save(saved)
        await uow.commit()

    async with make_uow() as uow:
        loaded = await uow.catalog.get(1)
    assert loaded.payees["landlord"].name == "Landlord"
    assert not loaded.has_catalog("landlord")
    assert loaded.has_catalog("lidl")
    [card] = [s for s in loaded.payment_sources.values() if s.kind is PaymentSourceKind.CARD]
    assert (card.name, card.brand, card.last4) == ("VISA •0848", "VISA", "0848")
    assert loaded.cash().id is not None
    assert loaded.ensure_card("MASTERCARD", "0848") is card


async def test_saving_assigns_ids_to_new_sources_and_rekeys_them(make_uow: MakeUow) -> None:
    await add_user(make_uow)
    catalog = Catalog(user_id=1)
    card = catalog.ensure_card("VISA", "0848")
    cash = catalog.cash()
    assert set(catalog.payment_sources) == {"card:0848", "cash"}
    async with make_uow() as uow:
        await uow.catalog.save(catalog)

    assert card.id is not None and cash.id is not None
    assert catalog.payment_sources == {card.id: card, cash.id: cash}


async def test_a_renamed_source_is_saved_by_id(make_uow: MakeUow) -> None:
    await add_user(make_uow)
    async with make_uow() as uow:
        await uow.catalog.save(stocked_catalog())
        await uow.commit()
    async with make_uow() as uow:
        catalog = await uow.catalog.get(1)
        card = catalog.ensure_card(None, "0848")
        assert card.id is not None
        catalog.rename_source(card.id, "Joint card")
        await uow.catalog.save(catalog)
        assert catalog.renamed_sources == ()
        await uow.commit()

    async with make_uow() as uow:
        loaded = await uow.catalog.get(1)
    assert loaded.ensure_card(None, "0848").name == "Joint card"
    assert loaded.cash().name == "Cash"


async def test_a_new_source_renamed_before_the_first_save_is_saved_with_the_name(
    make_uow: MakeUow,
) -> None:
    await add_user(make_uow)
    catalog = Catalog(user_id=1)
    catalog.ensure_card("VISA", "0848")
    catalog.rename_source("card:0848", "Joint card")
    async with make_uow() as uow:
        await uow.catalog.save(catalog)
        await uow.commit()

    async with make_uow() as uow:
        assert (await uow.catalog.get(1)).ensure_card(None, "0848").name == "Joint card"


async def test_a_user_has_one_card_per_ending_and_one_cash_source(make_uow: MakeUow) -> None:
    await add_user(make_uow)
    async with make_uow() as uow:
        await uow.catalog.save(stocked_catalog())
        await uow.commit()
    twin = Catalog(user_id=1)
    twin.payment_sources["x"] = PaymentSource(
        kind=PaymentSourceKind.CARD, name="Again", brand="VISA", last4="0848"
    )
    second_cash = Catalog(user_id=1)
    second_cash.payment_sources["x"] = PaymentSource(kind=PaymentSourceKind.CASH, name="Wallet")

    async with make_uow() as uow:
        with pytest.raises(UniqueViolationError):
            await uow.catalog.save(twin)
    async with make_uow() as uow:
        with pytest.raises(UniqueViolationError):
            await uow.catalog.save(second_cash)


@pytest.mark.parametrize(
    "source",
    [
        PaymentSource(kind=PaymentSourceKind.CASH, name="Cash with digits", last4="1234"),
        PaymentSource(kind=PaymentSourceKind.CARD, name="Short", last4="12"),
        PaymentSource(kind="wallet", name="Unknown kind"),  # type: ignore[arg-type]
    ],
    ids=["cash-with-last4", "short-last4", "unknown-kind"],
)
async def test_the_database_refuses_a_malformed_source(make_uow: MakeUow, source) -> None:
    await add_user(make_uow)
    catalog = Catalog(user_id=1)
    catalog.payment_sources["x"] = source
    async with make_uow() as uow:
        with pytest.raises(CheckViolationError):
            await uow.catalog.save(catalog)


async def test_two_users_may_use_the_same_card_ending_and_each_has_cash(make_uow: MakeUow) -> None:
    await add_user(make_uow, 1)
    await add_user(make_uow, 2)
    for user_id in (1, 2):
        catalog = Catalog(user_id=user_id)
        catalog.ensure_card("VISA", "0848")
        catalog.cash()
        async with make_uow() as uow:
            await uow.catalog.save(catalog)
            await uow.commit()

    async with make_uow() as uow:
        first, second = await uow.catalog.get(1), await uow.catalog.get(2)
    assert set(first.payment_sources).isdisjoint(second.payment_sources)
    assert len(first.payment_sources) == len(second.payment_sources) == 2


async def test_a_card_added_by_hand_is_saved_without_digits_and_gets_its_id(
    make_uow: MakeUow,
) -> None:
    await add_user(make_uow)
    catalog = Catalog(user_id=1)
    revolut, n26 = catalog.add_card("Revolut"), catalog.add_card("N26")

    async with make_uow() as uow:
        await uow.catalog.save(catalog)
        await uow.commit()

    assert revolut.id is not None and n26.id is not None and revolut.id != n26.id
    assert set(catalog.payment_sources) == {revolut.id, n26.id}
    async with make_uow() as uow:
        loaded = await uow.catalog.get(1)
    assert loaded == catalog
    assert (loaded.payment_sources[revolut.id].last4, loaded.payment_sources[revolut.id].brand) == (
        None,
        None,
    )


async def test_a_renamed_hand_added_card_is_saved_by_id(make_uow: MakeUow) -> None:
    await add_user(make_uow)
    catalog = Catalog(user_id=1)
    card = catalog.add_card("Revolut")
    async with make_uow() as uow:
        await uow.catalog.save(catalog)
        await uow.commit()

    async with make_uow() as uow:
        loaded = await uow.catalog.get(1)
        loaded.rename_source(card.id, "Revolut Joint")
        await uow.catalog.save(loaded)
        await uow.commit()

    async with make_uow() as uow:
        assert (await uow.catalog.get(1)).payment_sources[card.id].name == "Revolut Joint"


async def test_the_database_refuses_two_sources_of_a_user_with_the_same_name_ignoring_case(
    make_uow: MakeUow,
) -> None:
    await add_user(make_uow, 1)
    await add_user(make_uow, 2)
    first = Catalog(user_id=1)
    first.add_card("Revolut")
    async with make_uow() as uow:
        await uow.catalog.save(first)
        await uow.commit()
    clash = Catalog(user_id=1)
    clash.payment_sources["x"] = PaymentSource(kind=PaymentSourceKind.CARD, name="REVOLUT")
    other_user = Catalog(user_id=2)
    other_user.add_card("Revolut")

    async with make_uow() as uow:
        with pytest.raises(UniqueViolationError):
            await uow.catalog.save(clash)
    async with make_uow() as uow:
        await uow.catalog.save(other_user)  # another user's names are their own


async def test_payment_sources_lists_cash_first_then_cards_by_name_for_one_user(
    make_uow: MakeUow,
) -> None:
    await add_user(make_uow, 1)
    await add_user(make_uow, 2)
    catalog = Catalog(user_id=1)
    catalog.add_card("revolut")
    catalog.ensure_card("VISA", "0848")
    catalog.add_card("Amex")
    catalog.cash()
    stranger = Catalog(user_id=2)
    stranger.add_card("Other")
    async with make_uow() as uow:
        await uow.catalog.save(catalog)
        await uow.catalog.save(stranger)
        await uow.commit()

    async with make_uow() as uow:
        options = await uow.catalog.payment_sources(1)

    assert [(o.name, o.kind) for o in options] == [
        ("Cash", "cash"),
        ("Amex", "card"),
        ("revolut", "card"),
        ("VISA •0848", "card"),
    ]
    assert {o.id for o in options} == {s.id for s in catalog.payment_sources.values()}
    async with make_uow() as uow:
        assert await uow.catalog.payment_sources(3) == []
