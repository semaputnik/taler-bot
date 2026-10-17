"""The `Catalog` aggregate as plain Python: no database."""

import pytest

from src.domain.catalog import Catalog, Product
from src.domain.enums import PaymentSourceKind, ProductCategory
from src.exception import (
    InvalidEdit,
    InvalidPaymentSource,
    UnknownPayee,
    UnknownPaymentSource,
    UnknownProduct,
)


def ensure_milk(catalog: Catalog, **fields) -> Product:
    args = {
        "payee_key": "mercadona",
        "product_key": "mercadona::leche",
        "name_raw": "LECHE ENTERA",
        "name": "Whole milk",
        "category": ProductCategory.DAIRY,
        "unit": "l",
    } | fields
    return catalog.ensure_product(**args)


def test_ensure_payee_creates_it_on_first_sight():
    catalog = Catalog(user_id=1)

    payee = catalog.ensure_payee("mercadona", "Mercadona", tax_id="A-46103834")

    assert catalog.payees["mercadona"] is payee
    assert (payee.name, payee.tax_id, payee.id) == ("Mercadona", "A-46103834", None)


def test_ensure_payee_never_overwrites_an_existing_payee():
    catalog = Catalog(user_id=1)
    first = catalog.ensure_payee("mercadona", "My Mercadona")

    again = catalog.ensure_payee("mercadona", "MERCADONA, S.A.", legal_name="Mercadona S.A.")

    assert again is first
    assert (again.name, again.legal_name) == ("My Mercadona", None)


def test_ensure_product_creates_it_on_first_sight():
    catalog = Catalog(user_id=1)
    catalog.ensure_payee("mercadona", "Mercadona")

    product = ensure_milk(catalog, created_by_receipt_id=7)

    assert catalog.products["mercadona::leche"] is product
    assert (product.payee_key, product.name, product.category, product.unit) == (
        "mercadona",
        "Whole milk",
        ProductCategory.DAIRY,
        "l",
    )
    assert product.created_by_receipt_id == 7


def test_second_ensure_product_with_a_different_name_does_not_overwrite():
    catalog = Catalog(user_id=1)
    catalog.ensure_payee("mercadona", "Mercadona")
    first = ensure_milk(catalog, name="Milk (my name)", category=ProductCategory.DRINKS)

    again = ensure_milk(catalog, name="Whole milk", category=ProductCategory.DAIRY, unit="pcs")

    assert again is first
    assert (again.name, again.category, again.unit) == (
        "Milk (my name)",
        ProductCategory.DRINKS,
        "l",
    )
    assert len(catalog.products) == 1


def test_ensure_product_needs_its_payee_in_the_catalog():
    catalog = Catalog(user_id=1)

    with pytest.raises(UnknownPayee):
        ensure_milk(catalog)


def test_remove_unreferenced_marks_only_keys_the_catalog_knows():
    catalog = Catalog(user_id=1)
    catalog.ensure_payee("mercadona", "Mercadona")
    ensure_milk(catalog)
    ensure_milk(catalog, product_key="mercadona::pan", name_raw="PAN")

    catalog.remove_unreferenced({"mercadona::leche", "lidl::unknown"})

    assert set(catalog.products) == {"mercadona::pan"}
    assert catalog.removed_product_keys == frozenset({"mercadona::leche"})


def test_ensuring_a_product_marked_for_removal_keeps_it():
    catalog = Catalog(user_id=1)
    catalog.ensure_payee("mercadona", "Mercadona")
    first = ensure_milk(catalog)
    catalog.remove_unreferenced({"mercadona::leche"})

    again = ensure_milk(catalog, name="Another name")

    assert again is first
    assert again.name == "Whole milk"
    assert catalog.removed_product_keys == frozenset()


def stocked() -> Catalog:
    catalog = Catalog(user_id=1)
    catalog.ensure_payee("mercadona", "Mercadona")
    ensure_milk(catalog)
    ensure_milk(catalog, product_key="mercadona::pan", name_raw="PAN", name="Bread")
    return catalog


def test_rename_product_strips_the_name_and_marks_it_changed():
    catalog = stocked()

    catalog.rename_product("mercadona::leche", "  Oat milk  ")

    assert catalog.products["mercadona::leche"].name == "Oat milk"
    assert [p.product_key for p in catalog.changed_products] == ["mercadona::leche"]


def test_set_category_changes_it_and_marks_it_changed():
    catalog = stocked()

    catalog.set_category("mercadona::pan", ProductCategory.BAKERY)

    assert catalog.products["mercadona::pan"].category is ProductCategory.BAKERY
    assert [p.product_key for p in catalog.changed_products] == ["mercadona::pan"]


@pytest.mark.parametrize("name", ["", "   ", "\n"])
def test_rename_product_refuses_an_empty_name(name):
    catalog = stocked()

    with pytest.raises(InvalidEdit):
        catalog.rename_product("mercadona::leche", name)

    assert catalog.products["mercadona::leche"].name == "Whole milk"
    assert catalog.changed_products == ()


def test_changing_an_unknown_product_raises():
    catalog = stocked()

    with pytest.raises(UnknownProduct):
        catalog.rename_product("mercadona::nope", "x")
    with pytest.raises(UnknownProduct):
        catalog.set_category("mercadona::nope", ProductCategory.OTHER)


def test_mark_saved_clears_the_changed_products():
    catalog = stocked()
    catalog.rename_product("mercadona::leche", "Oat milk")

    catalog.mark_saved()

    assert catalog.changed_products == ()


def test_ensure_product_of_a_changed_product_keeps_the_change():
    catalog = stocked()
    catalog.rename_product("mercadona::leche", "Oat milk")

    again = ensure_milk(catalog, name="Whole milk")

    assert again.name == "Oat milk"
    assert len(catalog.changed_products) == 1


def test_a_changed_product_marked_for_removal_is_not_saved_as_changed():
    catalog = stocked()
    catalog.rename_product("mercadona::leche", "Oat milk")

    catalog.remove_unreferenced({"mercadona::leche"})

    assert catalog.changed_products == ()


def test_has_catalog_is_true_for_a_payee_with_products_only():
    catalog = Catalog(user_id=1)
    catalog.ensure_payee("mercadona", "Mercadona")
    catalog.ensure_payee("landlord", "Landlord")
    ensure_milk(catalog)

    assert catalog.has_catalog("mercadona")
    assert not catalog.has_catalog("landlord")
    assert not catalog.has_catalog("nobody")


# --- payment sources --------------------------------------------------------------------


def test_ensure_card_names_it_by_brand_and_digits():
    catalog = Catalog(user_id=1)

    card = catalog.ensure_card("visa", "0848")

    assert (card.kind, card.name, card.brand, card.last4, card.id) == (
        PaymentSourceKind.CARD,
        "VISA •0848",
        "VISA",
        "0848",
        None,
    )
    assert list(catalog.payment_sources.values()) == [card]


def test_ensure_card_without_a_brand_is_named_by_the_digits():
    catalog = Catalog(user_id=1)

    assert catalog.ensure_card(None, "1111").name == "•1111"
    assert catalog.ensure_card("  ", "2222").name == "•2222"


def test_ensure_card_is_idempotent_by_last4_and_never_overwrites():
    catalog = Catalog(user_id=1)
    first = catalog.ensure_card("VISA", "0848")
    catalog.rename_source("card:0848", "Ann's card")

    again = catalog.ensure_card("MASTERCARD", "0848")

    assert again is first
    assert (again.name, again.brand) == ("Ann's card", "VISA")
    assert len(catalog.payment_sources) == 1


@pytest.mark.parametrize("last4", ["", "123", "12345", "12a4", "١٢٣٤"])
def test_ensure_card_needs_four_digits(last4):
    with pytest.raises(InvalidPaymentSource):
        Catalog(user_id=1).ensure_card("VISA", last4)


def test_there_is_one_cash_source_created_on_first_use():
    catalog = Catalog(user_id=1)
    assert catalog.payment_sources == {}

    cash = catalog.cash()

    assert (cash.kind, cash.name, cash.last4) == (PaymentSourceKind.CASH, "Cash", None)
    assert catalog.cash() is cash
    assert len(catalog.payment_sources) == 1


def test_rename_source_strips_the_name_and_marks_it_changed():
    catalog = Catalog(user_id=1)
    catalog.ensure_card("VISA", "0848")

    renamed = catalog.rename_source("card:0848", "  Joint card ")

    assert renamed.name == "Joint card"
    assert catalog.renamed_sources == (renamed,)


@pytest.mark.parametrize("name", ["", "  "])
def test_rename_source_refuses_an_empty_name(name):
    catalog = Catalog(user_id=1)
    catalog.ensure_card("VISA", "0848")

    with pytest.raises(InvalidEdit):
        catalog.rename_source("card:0848", name)

    assert catalog.payment_sources["card:0848"].name == "VISA •0848"
    assert catalog.renamed_sources == ()


def test_rename_unknown_source_raises():
    with pytest.raises(UnknownPaymentSource):
        Catalog(user_id=1).rename_source(5, "x")


def test_assign_source_id_moves_a_new_source_under_its_id_and_keeps_its_rename():
    catalog = Catalog(user_id=1)
    card = catalog.ensure_card("VISA", "0848")
    cash = catalog.cash()
    catalog.rename_source("card:0848", "Joint card")

    catalog.assign_source_id(card, 7)
    catalog.assign_source_id(cash, 8)

    assert catalog.payment_sources == {7: card, 8: cash}
    assert (card.id, cash.id) == (7, 8)
    assert catalog.renamed_sources == (card,)
    assert catalog.rename_source(7, "Again").name == "Again"


def test_mark_saved_clears_the_renamed_sources():
    catalog = Catalog(user_id=1)
    catalog.ensure_card("VISA", "0848")
    catalog.rename_source("card:0848", "Joint card")

    catalog.mark_saved()

    assert catalog.renamed_sources == ()


# --- the source a receipt's card ending points at -------------------------------------------


def test_source_for_a_card_ending_is_the_card():
    catalog = Catalog(user_id=1)

    source = catalog.source_for("visa", "0848")

    assert source is catalog.ensure_card("VISA", "0848")
    assert source.kind is PaymentSourceKind.CARD


def test_source_for_no_card_ending_is_cash_whatever_the_brand():
    catalog = Catalog(user_id=1)

    assert catalog.source_for(None, None) is catalog.cash()
    assert catalog.source_for("VISA", None) is catalog.cash()
    assert len(catalog.payment_sources) == 1


# --- a payee typed by hand ------------------------------------------------------------------


def test_the_slug_helper_is_shared_with_normalize():
    from src.domain import normalize, slug

    assert normalize.slug is slug.slug
    assert slug.slug("  Café & Bar  ") == "cafe-and-bar"


def test_ensure_payee_named_keys_the_payee_by_the_slug_of_the_typed_name():
    catalog = Catalog(user_id=1)

    payee = catalog.ensure_payee_named("  Café Granja ")

    assert (payee.payee_key, payee.name) == ("cafe-granja", "Café Granja")
    assert catalog.payees == {"cafe-granja": payee}


def test_ensure_payee_named_reuses_a_payee_whatever_the_case():
    catalog = Catalog(user_id=1)
    existing = catalog.ensure_payee("mercadona", "Mercadona")

    assert catalog.ensure_payee_named("MERCADONA") is existing
    assert catalog.ensure_payee_named("mercadona") is existing
    assert len(catalog.payees) == 1
    assert existing.name == "Mercadona"


@pytest.mark.parametrize("name", ["", "   ", "!!!", "☕"])
def test_ensure_payee_named_needs_letters_or_digits(name):
    catalog = Catalog(user_id=1)

    with pytest.raises(InvalidEdit):
        catalog.ensure_payee_named(name)

    assert catalog.payees == {}


# --- a card added by hand -------------------------------------------------------------------


def test_add_card_makes_a_card_without_brand_and_digits():
    catalog = Catalog(user_id=1)

    card = catalog.add_card("  Revolut ")

    assert (card.kind, card.name, card.brand, card.last4, card.id) == (
        PaymentSourceKind.CARD,
        "Revolut",
        None,
        None,
        None,
    )
    assert list(catalog.payment_sources.values()) == [card]


@pytest.mark.parametrize("name", ["", "   "])
def test_add_card_needs_a_name(name):
    catalog = Catalog(user_id=1)

    with pytest.raises(InvalidPaymentSource):
        catalog.add_card(name)

    assert catalog.payment_sources == {}


def test_add_card_refuses_a_name_in_use_whatever_the_case():
    catalog = Catalog(user_id=1)
    catalog.ensure_card("VISA", "0848")
    catalog.cash()
    catalog.add_card("Revolut")

    for name in ("revolut", " REVOLUT ", "visa •0848", "cash"):
        with pytest.raises(InvalidPaymentSource):
            catalog.add_card(name)

    assert len(catalog.payment_sources) == 3


def test_two_hand_added_cards_have_their_own_temporary_keys_and_ids():
    catalog = Catalog(user_id=1)
    first, second = catalog.add_card("Revolut"), catalog.add_card("N26")

    catalog.assign_source_id(first, 4)
    catalog.assign_source_id(second, 5)

    assert catalog.payment_sources == {4: first, 5: second}


def test_rename_source_refuses_a_name_another_source_has():
    catalog = Catalog(user_id=1)
    catalog.ensure_card("VISA", "0848")
    catalog.add_card("Revolut")

    with pytest.raises(InvalidPaymentSource):
        catalog.rename_source("card:0848", "REVOLUT")

    assert catalog.payment_sources["card:0848"].name == "VISA •0848"
    assert catalog.renamed_sources == ()


def test_rename_source_may_change_only_the_case_of_its_own_name():
    catalog = Catalog(user_id=1)
    catalog.add_card("revolut")
    key = next(iter(catalog.payment_sources))

    assert catalog.rename_source(key, "Revolut").name == "Revolut"


def test_payee_and_source_look_up_what_the_catalog_holds_or_raise():
    catalog = Catalog(user_id=1)
    payee = catalog.ensure_payee("lidl", "Lidl")
    cash = catalog.cash()

    assert catalog.payee("lidl") is payee
    assert catalog.source("cash") is cash
    with pytest.raises(UnknownPayee):
        catalog.payee("aldi")
    with pytest.raises(UnknownPaymentSource):
        catalog.source(7)
