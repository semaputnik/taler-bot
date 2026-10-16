from datetime import date
from typing import Protocol

from src.domain.receipt import Receipt


class ReceiptRepository(Protocol):
    """Loads and saves the whole `Receipt` aggregate. Never commits."""

    async def get(self, receipt_id: int) -> Receipt | None:
        """The whole aggregate, soft-deleted included."""
        ...

    async def add(self, receipt: Receipt) -> Receipt:
        """Insert a new receipt with its parts and set their ids."""
        ...

    async def save(self, receipt: Receipt) -> None:
        """Write what changed since `get`; the aggregate says what."""
        ...

    async def find_by_key(self, user_id: int, receipt_key: str) -> Receipt | None:
        """The user's parsed, not deleted receipt with this key."""
        ...

    async def find_near(self, user_id: int, store_key: str, day: date) -> list[Receipt]:
        """Same store, same day (user's timezone); not deleted, not merged."""
        ...

    async def find_by_message(self, user_id: int, message_id: int) -> Receipt | None: ...

    async def link_message(self, receipt_id: int, user_id: int, message_id: int) -> None: ...

    async def photo_exists(self, user_id: int, telegram_file_unique_id: str) -> bool: ...
