import asyncio
import os
import secrets
from pathlib import Path

from src.integration.storage.interface import StorageError

TRASH_DIR = ".trash"


class LocalPhotoStorage:
    """Photos as files under `root`. Blocking file I/O runs in a worker thread."""

    def __init__(self, root: Path) -> None:
        self._root = root

    async def save(self, relative_path: str, data: bytes) -> None:
        await asyncio.to_thread(self._save, relative_path, data)

    async def read(self, relative_path: str) -> bytes:
        return await asyncio.to_thread(self._read, relative_path)

    async def trash(self, relative_path: str) -> None:
        await asyncio.to_thread(self._trash, relative_path)

    def _resolve(self, relative_path: str, base: Path | None = None) -> Path:
        base = base or self._root
        path = Path(relative_path)
        if not relative_path or path.is_absolute() or ".." in path.parts:
            raise StorageError(f"path leaves the storage root: {relative_path!r}")
        return base / path

    def _save(self, relative_path: str, data: bytes) -> None:
        final = self._resolve(relative_path)
        temp = final.with_name(f"{final.name}.tmp-{secrets.token_hex(4)}")
        try:
            final.parent.mkdir(parents=True, exist_ok=True)
            temp.write_bytes(data)
            os.replace(temp, final)
        except OSError as exc:
            raise StorageError(f"could not save {relative_path}") from exc
        finally:
            temp.unlink(missing_ok=True)

    def _read(self, relative_path: str) -> bytes:
        try:
            return self._resolve(relative_path).read_bytes()
        except OSError as exc:
            raise StorageError(f"could not read {relative_path}") from exc

    def _trash(self, relative_path: str) -> None:
        source = self._resolve(relative_path)
        target = self._resolve(relative_path, self._root / TRASH_DIR)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(source, target)
        except OSError as exc:
            raise StorageError(f"could not trash {relative_path}") from exc
