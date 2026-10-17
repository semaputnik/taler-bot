"""ORM rows <-> the `Catalog` aggregate. ORM objects never leave the `database` package."""

from collections.abc import Iterable

from src.database.models import Store as StoreRow
from src.database.models import StoreProduct as ProductRow
from src.domain.catalog import Catalog, Product, Store
from src.domain.enums import ProductCategory


def to_catalog(
    user_id: int, store_rows: Iterable[StoreRow], product_rows: Iterable[ProductRow]
) -> Catalog:
    catalog = Catalog(user_id=user_id)
    key_by_store_id: dict[int, str] = {}
    for row in store_rows:
        key_by_store_id[row.id] = row.store_key
        catalog.stores[row.store_key] = Store(
            id=row.id,
            store_key=row.store_key,
            name=row.name,
            legal_name=row.legal_name,
            tax_id=row.tax_id,
            address=row.address,
        )
    for row in product_rows:
        catalog.products[row.product_key] = Product(
            id=row.id,
            store_key=key_by_store_id[row.store_id],
            product_key=row.product_key,
            name_raw=row.name_raw,
            name=row.name,
            category=ProductCategory(row.category),
            unit=row.unit,
            created_by_receipt_id=row.created_by_receipt_id,
        )
    return catalog


def to_store_row(user_id: int, store: Store) -> StoreRow:
    return StoreRow(
        user_id=user_id,
        store_key=store.store_key,
        name=store.name,
        legal_name=store.legal_name,
        tax_id=store.tax_id,
        address=store.address,
    )


def to_product_row(user_id: int, store_id: int, product: Product) -> ProductRow:
    return ProductRow(
        user_id=user_id,
        store_id=store_id,
        product_key=product.product_key,
        name_raw=product.name_raw,
        name=product.name,
        category=str(product.category),  # the database CHECK decides what is valid
        unit=product.unit,
        created_by_receipt_id=product.created_by_receipt_id,
    )
