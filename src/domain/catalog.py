"""The `Catalog` aggregate: one user's stores and the products seen in them.

Percival & Gregory, *Architecture Patterns with Python*, ch. 7. The catalog outlives any
receipt and is never overwritten by a parse: `ensure_*` creates on first sight and leaves
an existing store or product alone, so names and categories fixed by hand stay fixed.

Stored parts carry an optional `id` (None until the repository inserts them). A product
that a receipt change no longer uses is marked with `remove_unreferenced`; the repository
deletes it on `save`, and the database refuses when a receipt item still references it.
A hand edit (`rename_product`, `set_category`) marks the product as changed; the repository
updates the changed products on `save`. The repository calls `mark_saved()` afterwards.
"""

from dataclasses import dataclass, field

from src.domain.enums import Category
from src.exception import InvalidEdit, UnknownProduct, UnknownStore


@dataclass
class Store:
    store_key: str
    name: str
    legal_name: str | None = None
    tax_id: str | None = None
    address: str | None = None
    id: int | None = None


@dataclass
class Product:
    store_key: str
    product_key: str
    name_raw: str
    name: str
    category: Category = Category.OTHER
    unit: str = "pcs"
    # Lets a re-parse remove products that only a misread of this receipt created.
    created_by_receipt_id: int | None = None
    id: int | None = None


@dataclass
class Catalog:
    user_id: int
    stores: dict[str, Store] = field(default_factory=dict)
    products: dict[str, Product] = field(default_factory=dict)
    _removed: dict[str, Product] = field(default_factory=dict, repr=False, compare=False)
    _changed: dict[str, Product] = field(default_factory=dict, repr=False, compare=False)

    def ensure_store(
        self,
        store_key: str,
        name: str,
        legal_name: str | None = None,
        tax_id: str | None = None,
        address: str | None = None,
    ) -> Store:
        store = self.stores.get(store_key)
        if store is None:
            store = Store(
                store_key=store_key,
                name=name,
                legal_name=legal_name,
                tax_id=tax_id,
                address=address,
            )
            self.stores[store_key] = store
        return store

    def ensure_product(
        self,
        store_key: str,
        product_key: str,
        name_raw: str,
        name: str,
        category: Category,
        unit: str,
        created_by_receipt_id: int | None = None,
    ) -> Product:
        product = self.products.get(product_key)
        if product is not None:
            return product
        if product_key in self._removed:  # marked earlier and wanted again: keep it as it is
            product = self.products[product_key] = self._removed.pop(product_key)
            return product
        if store_key not in self.stores:
            raise UnknownStore(f"No store {store_key!r} in the catalog of user {self.user_id}")
        product = Product(
            store_key=store_key,
            product_key=product_key,
            name_raw=name_raw,
            name=name,
            category=category,
            unit=unit,
            created_by_receipt_id=created_by_receipt_id,
        )
        self.products[product_key] = product
        return product

    def remove_unreferenced(self, product_keys: set[str] | frozenset[str]) -> None:
        """Mark the known products among `product_keys` for removal; unknown keys are ignored."""
        for key in product_keys:
            product = self.products.pop(key, None)
            if product is not None:
                self._removed[key] = product
                self._changed.pop(key, None)  # a removed product has nothing to update

    def rename_product(self, product_key: str, name: str) -> Product:
        """Give the product a readable name by hand (stripped, not empty)."""
        product = self._product(product_key)
        name = name.strip()
        if not name:
            raise InvalidEdit("a product name cannot be empty")
        product.name = name
        self._changed[product_key] = product
        return product

    def set_category(self, product_key: str, category: Category) -> Product:
        product = self._product(product_key)
        product.category = category
        self._changed[product_key] = product
        return product

    def _product(self, product_key: str) -> Product:
        product = self.products.get(product_key)
        if product is None:
            raise UnknownProduct(
                f"No product {product_key!r} in the catalog of user {self.user_id}"
            )
        return product

    @property
    def changed_products(self) -> tuple[Product, ...]:
        return tuple(self._changed.values())

    @property
    def removed_product_keys(self) -> frozenset[str]:
        return frozenset(self._removed)

    @property
    def removed_products(self) -> tuple[Product, ...]:
        return tuple(self._removed.values())

    def mark_saved(self) -> None:
        self._removed.clear()
        self._changed.clear()
