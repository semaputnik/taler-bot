from typing import Protocol

from src.domain.catalog import Catalog


class CatalogRepository(Protocol):
    async def get(self, user_id: int) -> Catalog:
        """The user's catalog; empty when they have no stores yet."""
        ...

    async def save(self, catalog: Catalog) -> None:
        """Insert the new stores and products, delete the ones marked for removal and update the
        name and category of the changed products (hand edits). Nothing else is updated."""
        ...
