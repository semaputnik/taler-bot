from typing import Protocol

from src.database.read_models import HistoryPage
from src.domain.receipt import Receipt


class ReceiptRepository(Protocol):
    """Loads and saves the whole `Receipt` aggregate. Never commits."""

    async def get(self, receipt_id: int) -> Receipt | None:
        """The whole aggregate, soft-deleted included."""
        ...

    async def add(self, receipt: Receipt) -> Receipt:
        """Insert a new receipt with its photo, parse and other parts and set their ids."""
        ...

    async def save(self, receipt: Receipt) -> None:
        """Write what changed since `get`; the aggregate says what."""
        ...

    async def find_by_key(self, user_id: int, receipt_key: str) -> Receipt | None:
        """The user's parsed, not deleted receipt with this key."""
        ...

    async def known_card_last4(self, user_id: int) -> set[str]:
        """Card endings of the user's parsed, not deleted receipts."""
        ...

    async def product_keys_in_items_elsewhere(
        self, user_id: int, product_keys: set[str], excluding_receipt_id: int
    ) -> set[str]:
        """Of `product_keys`, those that items of any other receipt (deleted ones too) use."""
        ...

    async def photo_exists(self, user_id: int, telegram_file_unique_id: str) -> bool: ...

    async def history(
        self,
        user_id: int,
        year: int,
        month: int,
        timezone: str,
        store_id: int | None = None,
        offset: int = 0,
        limit: int = 8,
    ) -> HistoryPage:
        """One page of the user's not deleted receipts of a month, newest first.

        A receipt belongs to the month of `coalesce(purchased_at, photo.received_at)` in the
        IANA time zone `timezone`. A fixed number of statements, whatever the month's size.
        """
        ...
