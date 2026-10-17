"""`CatalogService`: hand edits of the user's products (ADR-0001) and payment sources.

Every method is one Unit of Work: load the catalog, call one `Catalog` method, save, commit.
A product that is not in the user's own catalog counts as not found (`UnknownProduct`).
"""

from src.database.interfaces.uow import UnitOfWorkFactory
from src.domain.catalog import PaymentSource, Product
from src.domain.enums import ProductCategory
from src.exception import InvalidEdit
from src.services.results import ProductCard, SourceOption


class CatalogService:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def rename_product(self, user_id: int, product_key: str, name: str) -> ProductCard:
        """Give the product a readable name; it applies to every receipt showing it."""
        async with self._uow_factory() as uow:
            catalog = await uow.catalog.get(user_id)
            product = catalog.rename_product(product_key, name)
            await uow.catalog.save(catalog)
            await uow.commit()
            return _card(product)

    async def set_category(self, user_id: int, product_key: str, category: str) -> ProductCard:
        """Set the product's category from its name (`produce`, `dairy`, ...)."""
        try:
            parsed = ProductCategory(category)
        except ValueError:
            raise InvalidEdit(f"unknown category {category!r}") from None
        async with self._uow_factory() as uow:
            catalog = await uow.catalog.get(user_id)
            product = catalog.set_category(product_key, parsed)
            await uow.catalog.save(catalog)
            await uow.commit()
            return _card(product)

    async def add_card(self, user_id: int, name: str) -> SourceOption:
        """Add a card by name (no brand, no digits). The name is free when no other source of
        the user has it, ignoring case (`InvalidPaymentSource`)."""
        async with self._uow_factory() as uow:
            catalog = await uow.catalog.get(user_id)
            source = catalog.add_card(name)
            await uow.catalog.save(catalog)
            await uow.commit()
            return _option(source)

    async def rename_source(self, user_id: int, source_id: int, name: str) -> SourceOption:
        """Give a payment source a name; it shows on every expense that was paid with it."""
        async with self._uow_factory() as uow:
            catalog = await uow.catalog.get(user_id)
            source = catalog.rename_source(source_id, name)
            await uow.catalog.save(catalog)
            await uow.commit()
            return _option(source)


def _option(source: PaymentSource) -> SourceOption:
    assert source.id is not None  # saved
    return SourceOption(id=source.id, name=source.name, kind=str(source.kind))


def _card(product: Product) -> ProductCard:
    return ProductCard(
        product_key=product.product_key,
        store_key=product.payee_key,
        printed_name=product.name_raw,
        name=product.name,
        category=str(product.category),
    )
