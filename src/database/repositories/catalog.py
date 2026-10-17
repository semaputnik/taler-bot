from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.mapping.catalog import to_catalog, to_payee_row, to_product_row, to_source_row
from src.database.models import Payee as PayeeRow
from src.database.models import PaymentSource as SourceRow
from src.database.models import StoreProduct as ProductRow
from src.database.read_models import SourceOption
from src.domain.catalog import Catalog
from src.domain.enums import PaymentSourceKind


class SqlAlchemyCatalogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: int) -> Catalog:
        payees = await self._session.scalars(
            select(PayeeRow).where(PayeeRow.user_id == user_id).order_by(PayeeRow.id)
        )
        sources = await self._session.scalars(
            select(SourceRow).where(SourceRow.user_id == user_id).order_by(SourceRow.id)
        )
        products = await self._session.scalars(
            select(ProductRow).where(ProductRow.user_id == user_id)
        )
        return to_catalog(user_id, payees, sources, products)

    async def payment_sources(self, user_id: int) -> list[SourceOption]:
        rows = await self._session.execute(
            select(SourceRow.id, SourceRow.name, SourceRow.kind)
            .where(SourceRow.user_id == user_id)
            .order_by(
                (SourceRow.kind != PaymentSourceKind.CASH.value),
                func.lower(SourceRow.name),
                SourceRow.id,
            )
        )
        return [SourceOption(id=i, name=n, kind=k) for i, n, k in rows]

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

        for source in catalog.renamed_sources:
            if source.id is not None:
                await self._session.execute(
                    update(SourceRow).where(SourceRow.id == source.id).values(name=source.name)
                )

        new_payees = {
            s.payee_key: to_payee_row(catalog.user_id, s)
            for s in catalog.payees.values()
            if s.id is None
        }
        self._session.add_all(new_payees.values())
        await self._session.flush()
        for key, row in new_payees.items():
            catalog.payees[key].id = row.id

        new_sources = [
            (source, to_source_row(catalog.user_id, source))
            for source in catalog.payment_sources.values()
            if source.id is None
        ]
        self._session.add_all(row for _, row in new_sources)
        await self._session.flush()
        for source, row in new_sources:
            catalog.assign_source_id(source, row.id)

        new_products = {}
        for key, product in catalog.products.items():
            if product.id is None:
                payee_id = catalog.payees[product.payee_key].id
                assert payee_id is not None
                new_products[key] = to_product_row(catalog.user_id, payee_id, product)
        self._session.add_all(new_products.values())
        await self._session.flush()
        for key, row in new_products.items():
            catalog.products[key].id = row.id

        catalog.mark_saved()
