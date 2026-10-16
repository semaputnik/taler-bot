"""The `Catalog` aggregate as plain Python: no database."""

import pytest

from src.domain.catalog import Catalog, Product
from src.domain.enums import Category
from src.exception import UnknownStore


def ensure_milk(catalog: Catalog, **fields) -> Product:
    args = {
        "store_key": "mercadona",
        "product_key": "mercadona::leche",
        "name_raw": "LECHE ENTERA",
        "name": "Whole milk",
        "category": Category.DAIRY,
        "unit": "l",
    } | fields
    return catalog.ensure_product(**args)


def test_ensure_store_creates_it_on_first_sight():
    catalog = Catalog(user_id=1)

    store = catalog.ensure_store("mercadona", "Mercadona", tax_id="A-46103834")

    assert catalog.stores["mercadona"] is store
    assert (store.name, store.tax_id, store.id) == ("Mercadona", "A-46103834", None)


def test_ensure_store_never_overwrites_an_existing_store():
    catalog = Catalog(user_id=1)
    first = catalog.ensure_store("mercadona", "My Mercadona")

    again = catalog.ensure_store("mercadona", "MERCADONA, S.A.", legal_name="Mercadona S.A.")

    assert again is first
    assert (again.name, again.legal_name) == ("My Mercadona", None)


def test_ensure_product_creates_it_on_first_sight():
    catalog = Catalog(user_id=1)
    catalog.ensure_store("mercadona", "Mercadona")

    product = ensure_milk(catalog, created_by_receipt_id=7)

    assert catalog.products["mercadona::leche"] is product
    assert (product.store_key, product.name, product.category, product.unit) == (
        "mercadona",
        "Whole milk",
        Category.DAIRY,
        "l",
    )
    assert product.created_by_receipt_id == 7


def test_second_ensure_product_with_a_different_name_does_not_overwrite():
    catalog = Catalog(user_id=1)
    catalog.ensure_store("mercadona", "Mercadona")
    first = ensure_milk(catalog, name="Milk (my name)", category=Category.DRINKS)

    again = ensure_milk(catalog, name="Whole milk", category=Category.DAIRY, unit="pcs")

    assert again is first
    assert (again.name, again.category, again.unit) == ("Milk (my name)", Category.DRINKS, "l")
    assert len(catalog.products) == 1


def test_ensure_product_needs_its_store_in_the_catalog():
    catalog = Catalog(user_id=1)

    with pytest.raises(UnknownStore):
        ensure_milk(catalog)


def test_remove_unreferenced_marks_only_keys_the_catalog_knows():
    catalog = Catalog(user_id=1)
    catalog.ensure_store("mercadona", "Mercadona")
    ensure_milk(catalog)
    ensure_milk(catalog, product_key="mercadona::pan", name_raw="PAN")

    catalog.remove_unreferenced({"mercadona::leche", "lidl::unknown"})

    assert set(catalog.products) == {"mercadona::pan"}
    assert catalog.removed_product_keys == frozenset({"mercadona::leche"})


def test_ensuring_a_product_marked_for_removal_keeps_it():
    catalog = Catalog(user_id=1)
    catalog.ensure_store("mercadona", "Mercadona")
    first = ensure_milk(catalog)
    catalog.remove_unreferenced({"mercadona::leche"})

    again = ensure_milk(catalog, name="Another name")

    assert again is first
    assert again.name == "Whole milk"
    assert catalog.removed_product_keys == frozenset()
