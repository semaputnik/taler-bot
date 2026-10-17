"""`CatalogService`: hand edits of the user's products (ADR-0001).

Every method is one Unit of Work: load the catalog, call one `Catalog` method, save, commit.
A product that is not in the user's own catalog counts as not found (`UnknownProduct`).
"""

from src.database.interfaces.uow import UnitOfWorkFactory
from src.domain.catalog import Product
from src.domain.enums import Category
from src.exception import InvalidEdit
from src.services.results import ProductCard


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
            parsed = Category(category)
        except ValueError:
            raise InvalidEdit(f"unknown category {category!r}") from None
        async with self._uow_factory() as uow:
            catalog = await uow.catalog.get(user_id)
            product = catalog.set_category(product_key, parsed)
            await uow.catalog.save(catalog)
            await uow.commit()
            return _card(product)


def _card(product: Product) -> ProductCard:
    return ProductCard(
        product_key=product.product_key,
        store_key=product.store_key,
        printed_name=product.name_raw,
        name=product.name,
        category=str(product.category),
    )
