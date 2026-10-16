"""The ReceiptCard photo window through the real dispatcher on real Postgres."""

import pytest
from aiogram.methods import DeleteMessage, EditMessageMedia, EditMessageText
from aiogram.types import BufferedInputFile
from sqlalchemy import text

from src.bot.i18n import DEFAULT_LOCALE, create_translator_hub

USER = 7
ITEMS = "📋 Items"
PHOTO = "🖼 Photo"
DELETE = "🗑 Delete"
BACK = "◀ Back"
CLOSE = "✖ Close"
BYTES = b"jpeg-bytes"

i18n = create_translator_hub().get_translator_by_locale(DEFAULT_LOCALE)


@pytest.fixture(autouse=True)
async def _allowed(allow_user):
    await allow_user(USER)


@pytest.fixture
def forbid_disk_reads(tmp_storage, monkeypatch):
    """Arm a guard that fails the test if a stored photo is read from the disk afterwards."""

    def arm() -> None:
        async def read(relative_path: str) -> bytes:
            raise AssertionError(f"unexpected disk read: {relative_path}")

        monkeypatch.setattr(tmp_storage, "read", read)

    return arm


async def parsed(harness) -> int:
    await harness.send_photo(user_id=USER, file_id="f1", data=BYTES)
    await harness.tasks.drain()
    return harness.last_keyboard()[0]


async def stored_file_id(session_factory) -> str:
    async with session_factory() as session:
        row = await session.execute(text("select telegram_file_id from receipt_photos"))
        return row.scalar_one()


def last_text(harness) -> str:
    for call in reversed(harness.session.calls):
        if isinstance(call, EditMessageText) or call in harness.sent_messages:
            return call.text
    raise AssertionError("nothing sent")


async def test_the_photo_button_sends_the_stored_photo_by_file_id_without_the_disk(
    harness, forbid_disk_reads
):
    await parsed(harness)
    forbid_disk_reads()

    await harness.tap(USER, PHOTO)

    (sent,) = harness.sent_photos
    assert sent.photo == "f1"
    assert harness.button_texts() == [BACK]
    assert harness.session.rejected_calls == []


async def test_a_refused_file_id_falls_back_to_the_stored_bytes(harness, session_factory):
    await parsed(harness)
    harness.session.rejected_file_ids.add("f1")

    await harness.tap(USER, PHOTO)

    attempt, upload = harness.sent_photos
    assert attempt.photo == "f1"
    assert isinstance(upload.photo, BufferedInputFile)
    assert upload.photo.data == BYTES
    assert harness.button_texts() == [BACK]
    assert await stored_file_id(session_factory) == "f1"  # nothing is written back


async def test_back_returns_to_the_card(harness):
    await parsed(harness)
    await harness.tap(USER, PHOTO)

    await harness.tap(USER, BACK)

    assert "Consum" in last_text(harness)
    assert harness.button_texts() == [ITEMS, PHOTO, DELETE, CLOSE]
    assert [c for c in harness.session.calls if isinstance(c, DeleteMessage)]  # photo -> text


async def test_the_main_window_opens_the_photo_in_place(harness):
    await parsed(harness)
    await harness.tap(USER, DELETE)
    await harness.tap(USER, BACK)
    cards_before = len(harness.sent_messages)

    await harness.tap(USER, PHOTO)

    (edit,) = [c for c in harness.session.calls if isinstance(c, EditMessageMedia)]
    assert edit.media.media == "f1"
    assert len(harness.sent_messages) == cards_before
    assert harness.button_texts() == [BACK]


async def test_a_refused_file_id_falls_back_when_editing_the_card_into_the_photo(harness):
    await parsed(harness)
    await harness.tap(USER, DELETE)
    await harness.tap(USER, BACK)
    harness.session.rejected_file_ids.add("f1")

    await harness.tap(USER, PHOTO)

    first, second = [c for c in harness.session.calls if isinstance(c, EditMessageMedia)]
    assert first.media.media == "f1"
    assert isinstance(second.media.media, BufferedInputFile)
    assert second.media.media.data == BYTES
    assert harness.button_texts() == [BACK]


async def test_a_missing_file_shows_the_notice_instead_of_the_photo(harness, tmp_storage):
    await parsed(harness)
    harness.session.rejected_file_ids.add("f1")
    for path in tmp_storage._root.rglob("*.jpg"):
        path.unlink()

    await harness.tap(USER, PHOTO)

    assert harness.sent_messages[-1].text == i18n.get("card-photo-unavailable")
    assert [p.photo for p in harness.sent_photos] == ["f1"]  # the refused attempt only
    assert harness.button_texts() == [BACK]


async def test_a_missing_file_shows_the_notice_when_editing_the_card(harness, tmp_storage):
    await parsed(harness)
    await harness.tap(USER, DELETE)
    await harness.tap(USER, BACK)
    harness.session.rejected_file_ids.add("f1")
    for path in tmp_storage._root.rglob("*.jpg"):
        path.unlink()

    await harness.tap(USER, PHOTO)

    assert harness.sent_messages[-1].text == i18n.get("card-photo-unavailable")
    assert harness.button_texts() == [BACK]
    await harness.tap(USER, BACK)
    assert harness.button_texts() == [ITEMS, PHOTO, DELETE, CLOSE]
