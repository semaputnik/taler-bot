from typing import Protocol

from src.exception import IntegrationException


class StorageError(IntegrationException):
    """A photo could not be written, read or moved."""


class PhotoStorage(Protocol):
    """Photo bytes by path relative to the storage root (`yyyy/mm/receipt_....jpg`)."""

    async def save(self, relative_path: str, data: bytes) -> None:
        """Store the bytes; a failure leaves nothing at `relative_path`."""
        ...

    async def read(self, relative_path: str) -> bytes: ...

    async def trash(self, relative_path: str) -> None:
        """Move the photo out of the way (never delete it), keeping its relative path."""
        ...
