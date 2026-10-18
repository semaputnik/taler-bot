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
id yet, so it sits under a temporary key (`"cash"`, `"card:<last4>"`, or `"new-card:<name>"` for
a card added by hand) until the repository assigns the id with `assign_source_id`, which moves
it under the id. Read `source.id` after saving the catalog, never the temporary key.

Source names are unique per user ignoring case (the database has the same index); a hand-added
card has no brand and no last four digits, so a receipt never links to it.
"""

import re
from dataclasses import dataclass, field

from src.domain.enums import PaymentSourceKind, ProductCategory
from src.domain.slug import slug
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

    def payee(self, payee_key: str) -> Payee:
        """The payee with this key; `UnknownPayee` when the user has none."""
        payee = self.payees.get(payee_key)
        if payee is None:
            raise UnknownPayee(f"No payee {payee_key!r} in the catalog of user {self.user_id}")
        return payee

    def ensure_payee_named(self, name: str) -> Payee:
        """The payee a user typed: keyed by the slug of the name, so "mercadona" and "Mercadona"
        are one payee. An existing payee keeps its name."""
        name = name.strip()
        payee_key = slug(name)
        if not payee_key:
            raise InvalidEdit("a payee name needs letters or digits")
        return self.ensure_payee(payee_key, name)

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
        name = f"{brand} •{last4}" if brand else f"•{last4}"
        if self._name_taken(name):  # a card added by hand already has this name: keep both apart
            name = f"{name} (receipt)"
        source = PaymentSource(kind=PaymentSourceKind.CARD, name=name, brand=brand, last4=last4)
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

    def source(self, source_id: int | str) -> PaymentSource:
        """The payment source under this key (its id once stored); `UnknownPaymentSource`
        when the user has none."""
        source = self.payment_sources.get(source_id)
        if source is None:
            raise UnknownPaymentSource(
                f"No payment source {source_id!r} in the catalog of user {self.user_id}"
            )
        return source

    def add_card(self, name: str) -> PaymentSource:
        """A card the user added by hand: no brand, no last four digits, a name that no other
        source of the user has (ignoring case)."""
        name = name.strip()
        if not name:
            raise InvalidPaymentSource("a card needs a name")
        self._ensure_name_free(name)
        source = PaymentSource(kind=PaymentSourceKind.CARD, name=name)
        self.payment_sources[f"new-card:{name.lower()}"] = source
        return source

    def source_for(self, card_brand: str | None, card_last4: str | None) -> PaymentSource:
        """What a receipt was paid with: the card of its printed ending, else cash."""
        if card_last4:
            return self.ensure_card(card_brand, card_last4)
        return self.cash()

    def rename_source(self, source_id: int | str, name: str) -> PaymentSource:
        """Give a source a name by hand (stripped, not empty). `source_id` is its key."""
        source = self.source(source_id)
        name = name.strip()
        if not name:
            raise InvalidEdit("a payment source name cannot be empty")
        self._ensure_name_free(name, besides=source)
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

    def _ensure_name_free(self, name: str, besides: PaymentSource | None = None) -> None:
        if name.lower() == CASH_NAME.lower() and (
            besides is None or besides.kind is not PaymentSourceKind.CASH
        ):  # the cash source may not exist yet, but its name is reserved
            raise InvalidPaymentSource(f"the name {CASH_NAME!r} belongs to the cash source")
        if self._name_taken(name, besides):
            raise InvalidPaymentSource(f"a payment source named {name!r} exists")

    def _name_taken(self, name: str, besides: PaymentSource | None = None) -> bool:
        taken = name.lower()
        return any(
            other is not besides and other.name.lower() == taken
            for other in self.payment_sources.values()
        )

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
        self.payee(payee_key)
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
