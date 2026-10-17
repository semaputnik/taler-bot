from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.mapping.catalog import to_catalog, to_product_row, to_store_row
from src.database.models import Store as StoreRow
from src.database.models import StoreProduct as ProductRow
from src.domain.catalog import Catalog


class SqlAlchemyCatalogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: int) -> Catalog:
        stores = await self._session.scalars(select(StoreRow).where(StoreRow.user_id == user_id))
        products = await self._session.scalars(
            select(ProductRow).where(ProductRow.user_id == user_id)
        )
        return to_catalog(user_id, stores, products)

    async def save(self, catalog: Catalog) -> None:
        removed_ids = [p.id for p in catalog.removed_products if p.id is not None]
        if removed_ids:
            await self._session.execute(delete(ProductRow).where(ProductRow.id.in_(removed_ids)))

        for product in catalog.changed_products:
            if product.id is not None:
                await self._session.execute(
                    update(ProductRow)
                    .where(ProductRow.id == product.id)
                    .values(name=product.name, category=str(product.category))
                )

        new_stores = {
            s.store_key: to_store_row(catalog.user_id, s)
            for s in catalog.stores.values()
            if s.id is None
        }
        self._session.add_all(new_stores.values())
        await self._session.flush()
        for key, row in new_stores.items():
            catalog.stores[key].id = row.id

        new_products = {}
        for key, product in catalog.products.items():
            if product.id is None:
                store_id = catalog.stores[product.store_key].id
                assert store_id is not None
                new_products[key] = to_product_row(catalog.user_id, store_id, product)
        self._session.add_all(new_products.values())
        await self._session.flush()
        for key, row in new_products.items():
            catalog.products[key].id = row.id

        catalog.mark_saved()
