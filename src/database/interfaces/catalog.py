from datetime import datetime
from typing import Protocol

from src.database.read_models import SourceOption
from src.domain.catalog import Catalog, KnownStore


class CatalogRepository(Protocol):
    async def get(self, user_id: int) -> Catalog:
        """The user's catalog; empty when they have no payees, payment sources or products yet."""
        ...

    async def save(self, catalog: Catalog) -> None:
        """Insert the new payees, payment sources (they get their ids) and products, delete the
        products marked for removal, and update the name and category of the changed products
        and the name of the renamed sources (hand edits). Nothing else is updated."""
        ...

    async def known_stores(self, user_id: int, since: datetime) -> list[KnownStore]:
        """The stores of the user's live receipts bought at `since` or later (by
        `coalesce(purchased_at, received_at)`), by name, each with the products on those
        receipts' lines. One query."""
        ...

    async def payment_sources(self, user_id: int) -> list[SourceOption]:
        """The user's payment sources to pick from: cash first, then the cards by name."""
        ...
