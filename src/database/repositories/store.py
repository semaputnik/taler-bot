from sqlalchemy import delete, insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.dto.store import NewStoreDTO, NewStoreProductDTO, StoreDTO, StoreProductDTO
from src.database.models import Store, StoreProduct


class SqlAlchemyStoreRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, data: NewStoreDTO) -> StoreDTO:
        stmt = insert(Store).values(**data.model_dump()).returning(Store)
        store = (await self._session.execute(stmt)).scalar_one()
        return StoreDTO.model_validate(store)

    async def get(self, store_id: int) -> StoreDTO | None:
        store = await self._session.get(Store, store_id)
        return StoreDTO.model_validate(store) if store else None


class SqlAlchemyStoreProductRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, data: NewStoreProductDTO) -> StoreProductDTO:
        stmt = insert(StoreProduct).values(**data.model_dump()).returning(StoreProduct)
        product = (await self._session.execute(stmt)).scalar_one()
        return StoreProductDTO.model_validate(product)

    async def get(self, product_id: int) -> StoreProductDTO | None:
        product = await self._session.get(StoreProduct, product_id)
        return StoreProductDTO.model_validate(product) if product else None

    async def delete(self, product_id: int) -> None:
        await self._session.execute(delete(StoreProduct).where(StoreProduct.id == product_id))
