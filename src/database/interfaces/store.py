from typing import Protocol

from src.database.dto.store import NewStoreDTO, NewStoreProductDTO, StoreDTO, StoreProductDTO


class StoreRepository(Protocol):
    async def add(self, data: NewStoreDTO) -> StoreDTO: ...

    async def get(self, store_id: int) -> StoreDTO | None: ...


class StoreProductRepository(Protocol):
    async def add(self, data: NewStoreProductDTO) -> StoreProductDTO: ...

    async def get(self, product_id: int) -> StoreProductDTO | None: ...

    async def delete(self, product_id: int) -> None: ...
