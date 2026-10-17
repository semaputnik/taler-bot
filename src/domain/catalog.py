"""The `Catalog` aggregate: one user's payees, payment sources and the products seen in them.

Percival & Gregory, *Architecture Patterns with Python*, ch. 7. The catalog outlives any
receipt and is never overwritten by a parse: `ensure_*` creates on first sight and leaves
an existing payee, source or product alone, so names and categories fixed by hand stay fixed.

A payee is whoever received money; a payee with products is a store (ADR-0003). A payment
source is a card or cash. The catalog holds both next to the products.

Stored parts carry an optional `id` (None until the repository inserts them). A product
that a receipt change no longer uses is marked with `remove_unreferenced`; the repository
deletes it on `save`, and the database refuses when a receipt item still references it.
A hand edit (`rename_product`, `set_category`, `rename_source`) marks the part as changed;
the repository updates the changed ones on `save`. The repository calls `mark_saved()`
afterwards.

`payment_sources` is keyed by the source's id once it is stored. A source that is new has no
id yet, so it sits under a temporary key (`"cash"`, or `"card:<last4>"`) until the repository
assigns the id with `assign_source_id`, which moves it under the id. Read `source.id` after
saving the catalog, never the temporary key.
"""

import re
from dataclasses import dataclass, field

from src.domain.enums import PaymentSourceKind, ProductCategory
from src.exception import (
    InvalidEdit,
    InvalidPaymentSource,
    UnknownPayee,
    UnknownPaymentSource,
    UnknownProduct,
)

CASH_NAME = "Cash"
_CASH_KEY = "cash"
_LAST4 = re.compile(r"[0-9]{4}")


@dataclass
class Payee:
    """Whoever received the money. `payee_key` is the slug of its name, per user."""

    payee_key: str
    name: str
    legal_name: str | None = None
    tax_id: str | None = None
    address: str | None = None
    id: int | None = None


@dataclass
class PaymentSource:
    """What the money left from: a card (brand and last four digits) or the user's cash."""

    kind: PaymentSourceKind
    name: str
    brand: str | None = None
    last4: str | None = None
    id: int | None = None


@dataclass
class Product:
    payee_key: str
    product_key: str
    name_raw: str
    name: str
    category: ProductCategory = ProductCategory.OTHER
    unit: str = "pcs"
    # Lets a re-parse remove products that only a misread of this receipt created.
    created_by_receipt_id: int | None = None
    id: int | None = None


@dataclass
class Catalog:
    user_id: int
    payees: dict[str, Payee] = field(default_factory=dict)
    payment_sources: dict[int | str, PaymentSource] = field(default_factory=dict)
    products: dict[str, Product] = field(default_factory=dict)
    _removed: dict[str, Product] = field(default_factory=dict, repr=False, compare=False)
    _changed: dict[str, Product] = field(default_factory=dict, repr=False, compare=False)
    _renamed_sources: dict[int | str, PaymentSource] = field(
        default_factory=dict, repr=False, compare=False
    )

    def ensure_payee(
        self,
        payee_key: str,
        name: str,
        legal_name: str | None = None,
        tax_id: str | None = None,
        address: str | None = None,
    ) -> Payee:
        payee = self.payees.get(payee_key)
        if payee is None:
            payee = Payee(
                payee_key=payee_key,
                name=name,
                legal_name=legal_name,
                tax_id=tax_id,
                address=address,
            )
            self.payees[payee_key] = payee
        return payee

    def has_catalog(self, payee_key: str) -> bool:
        """True for a payee with products: a store."""
        return any(p.payee_key == payee_key for p in self.products.values())

    # --- payment sources ---------------------------------------------------------------

    def ensure_card(self, brand: str | None, last4: str) -> PaymentSource:
        """The user's card with these last four digits, created on first sight.

        The name is `"{BRAND} •{last4}"`, or `"•{last4}"` without a brand. An existing card
        is returned as it is, so a name the user chose stays and a brand never replaces it.
        """
        if not _LAST4.fullmatch(last4):
            raise InvalidPaymentSource(f"a card needs four digits, got {last4!r}")
        for source in self.payment_sources.values():
            if source.kind is PaymentSourceKind.CARD and source.last4 == last4:
                return source
        brand = (brand or "").strip().upper() or None
        source = PaymentSource(
            kind=PaymentSourceKind.CARD,
            name=f"{brand} •{last4}" if brand else f"•{last4}",
            brand=brand,
            last4=last4,
        )
        self.payment_sources[f"card:{last4}"] = source
        return source

    def cash(self) -> PaymentSource:
        """The user's one cash source, created on first use."""
        for source in self.payment_sources.values():
            if source.kind is PaymentSourceKind.CASH:
                return source
        source = PaymentSource(kind=PaymentSourceKind.CASH, name=CASH_NAME)
        self.payment_sources[_CASH_KEY] = source
        return source

    def source_for(self, card_brand: str | None, card_last4: str | None) -> PaymentSource:
        """What a receipt was paid with: the card of its printed ending, else cash."""
        if card_last4:
            return self.ensure_card(card_brand, card_last4)
        return self.cash()

    def rename_source(self, source_id: int | str, name: str) -> PaymentSource:
        """Give a source a name by hand (stripped, not empty). `source_id` is its key."""
        source = self.payment_sources.get(source_id)
        if source is None:
            raise UnknownPaymentSource(
                f"No payment source {source_id!r} in the catalog of user {self.user_id}"
            )
        name = name.strip()
        if not name:
            raise InvalidEdit("a payment source name cannot be empty")
        source.name = name
        self._renamed_sources[source_id] = source
        return source

    def assign_source_id(self, source: PaymentSource, source_id: int) -> None:
        """For the repository: a new source got its id; move it under the id."""
        for key, found in list(self.payment_sources.items()):
            if found is source:
                del self.payment_sources[key]
                if key in self._renamed_sources:
                    self._renamed_sources[source_id] = self._renamed_sources.pop(key)
        source.id = source_id
        self.payment_sources[source_id] = source

    # --- products ----------------------------------------------------------------------

    def ensure_product(
        self,
        payee_key: str,
        product_key: str,
        name_raw: str,
        name: str,
        category: ProductCategory,
        unit: str,
        created_by_receipt_id: int | None = None,
    ) -> Product:
        product = self.products.get(product_key)
        if product is not None:
            return product
        if product_key in self._removed:  # marked earlier and wanted again: keep it as it is
            product = self.products[product_key] = self._removed.pop(product_key)
            return product
        if payee_key not in self.payees:
            raise UnknownPayee(f"No payee {payee_key!r} in the catalog of user {self.user_id}")
        product = Product(
            payee_key=payee_key,
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

    def set_category(self, product_key: str, category: ProductCategory) -> Product:
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
    def renamed_sources(self) -> tuple[PaymentSource, ...]:
        return tuple(self._renamed_sources.values())

    @property
    def removed_product_keys(self) -> frozenset[str]:
        return frozenset(self._removed)

    @property
    def removed_products(self) -> tuple[Product, ...]:
        return tuple(self._removed.values())

    def mark_saved(self) -> None:
        self._removed.clear()
        self._changed.clear()
        self._renamed_sources.clear()
