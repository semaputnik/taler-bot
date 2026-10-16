"""LocalPhotoStorage on a tmp directory."""

import os
from pathlib import Path

import pytest

from src.integration.storage import LocalPhotoStorage, StorageError

PATH = "2026/10/receipt_2026-10-14_20-32-00_7.jpg"


@pytest.fixture
def storage(tmp_path: Path) -> LocalPhotoStorage:
    return LocalPhotoStorage(tmp_path / "receipts")


async def test_save_then_read_returns_the_same_bytes_and_creates_directories(storage, tmp_path):
    await storage.save(PATH, b"\xff\xd8photo")

    assert await storage.read(PATH) == b"\xff\xd8photo"
    assert (tmp_path / "receipts" / PATH).is_file()


async def test_save_leaves_no_temp_files_behind(storage, tmp_path):
    await storage.save(PATH, b"x")

    assert [p.name for p in (tmp_path / "receipts/2026/10").iterdir()] == [Path(PATH).name]


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
async def test_a_failed_write_leaves_nothing_at_the_final_path(storage, tmp_path):
    folder = tmp_path / "receipts/2026/10"
    folder.mkdir(parents=True)
    folder.chmod(0o500)
    try:
        with pytest.raises(StorageError):
            await storage.save(PATH, b"x")
    finally:
        folder.chmod(0o700)

    assert list(folder.iterdir()) == []


async def test_a_failure_while_writing_removes_the_temp_file(storage, tmp_path, monkeypatch):
    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr("src.integration.storage.local.os.replace", boom)
    with pytest.raises(StorageError):
        await storage.save(PATH, b"x")

    assert list((tmp_path / "receipts").rglob("*.*")) == []


async def test_read_of_a_missing_file_raises_storage_error(storage):
    with pytest.raises(StorageError):
        await storage.read(PATH)


async def test_trash_moves_the_file_keeping_the_relative_layout(storage, tmp_path):
    await storage.save(PATH, b"x")

    await storage.trash(PATH)

    assert not (tmp_path / "receipts" / PATH).exists()
    assert (tmp_path / "receipts/.trash" / PATH).read_bytes() == b"x"


async def test_trash_of_a_missing_file_raises_storage_error(storage):
    with pytest.raises(StorageError):
        await storage.trash(PATH)


@pytest.mark.parametrize("bad", ["../escape.jpg", "/etc/passwd", "2026/../../x.jpg", ""])
async def test_paths_escaping_the_root_are_refused(storage, bad):
    with pytest.raises(StorageError):
        await storage.save(bad, b"x")
    with pytest.raises(StorageError):
        await storage.read(bad)
    with pytest.raises(StorageError):
        await storage.trash(bad)
