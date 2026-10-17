"""The ReceiptCard photo window through the real dispatcher on real Postgres."""

import pytest
from aiogram.methods import DeleteMessage, EditMessageMedia
from aiogram.types import BufferedInputFile
from sqlalchemy import text

from src.bot.i18n import DEFAULT_LOCALE, create_translator_hub
from tests.stubs import fixture, output_of

USER = 7
ITEMS = "📋 Items"
REVIEW = "⚠️ Review (1)"
CATEGORY = "🏷 Category"
PHOTO = "🖼 Photo"
DELETE = "🗑 Delete"
CLOSE = "✖ Close"
REPARSE = "🔄 Re-parse"
BACK = "◀ Back"
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


async def stored_file_ids(session_factory) -> list[str]:
    async with session_factory() as session:
        rows = await session.execute(
            text("select telegram_file_id from receipt_photos order by id")
        )
        return [row[0] for row in rows]


async def older_card_photo_data(harness) -> tuple[int, str]:
    """Two receipts; return the first card's message id and its Photo button's callback data."""
    first_id = await parsed(harness)
    photo_data = next(
        b.callback_data
        for row in harness.last_keyboard()[1].inline_keyboard
        for b in row
        if b.text == PHOTO
    )
    raw = fixture("03")["raw"]
    harness.parser.default = output_of(raw | {"receipt": raw["receipt"] | {"number": "OTHER"}})
    await harness.send_photo(user_id=USER, file_id="f2", data=BYTES)
    await harness.tasks.drain()
    return first_id, photo_data


async def test_the_photo_button_edits_the_card_into_the_stored_photo_by_file_id(
    harness, forbid_disk_reads
):
    card_id = await parsed(harness)
    forbid_disk_reads()
    cards = len(harness.sent_messages)

    await harness.tap(USER, PHOTO)

    (edit,) = [c for c in harness.session.calls if isinstance(c, EditMessageMedia)]
    assert (edit.message_id, edit.media.media) == (card_id, "f1")
    assert len(harness.sent_messages) == cards
    assert harness.sent_photos == []
    assert harness.button_texts() == [BACK]
    assert harness.session.rejected_calls == []


async def test_the_photo_of_an_older_card_is_sent_as_a_new_message_by_file_id(
    harness, forbid_disk_reads
):
    first_id, photo_data = await older_card_photo_data(harness)
    forbid_disk_reads()

    await harness.press(USER, photo_data, first_id)

    (sent,) = harness.sent_photos
    assert sent.photo == "f1"
    assert harness.button_texts() == [BACK]
    assert harness.session.rejected_calls == []


async def test_a_refused_file_id_falls_back_to_the_stored_bytes(harness, session_factory):
    first_id, photo_data = await older_card_photo_data(harness)
    harness.session.rejected_file_ids.add("f1")

    await harness.press(USER, photo_data, first_id)

    attempt, upload = harness.sent_photos
    assert attempt.photo == "f1"
    assert isinstance(upload.photo, BufferedInputFile)
    assert upload.photo.data == BYTES
    assert harness.button_texts() == [BACK]
    assert await stored_file_ids(session_factory) == ["f1", "f2"]  # nothing is written back


async def test_back_returns_to_the_card(harness):
    await parsed(harness)
    await harness.tap(USER, PHOTO)

    await harness.tap(USER, BACK)

    assert "Consum" in harness.last_text()
    assert harness.button_texts() == [ITEMS, REVIEW, CATEGORY, PHOTO, DELETE, REPARSE, CLOSE]
    assert [c for c in harness.session.calls if isinstance(c, DeleteMessage)]  # photo -> text


async def test_the_main_window_opens_the_photo_in_place(harness):
    await parsed(harness)
    cards_before = len(harness.sent_messages)

    await harness.tap(USER, PHOTO)

    (edit,) = [c for c in harness.session.calls if isinstance(c, EditMessageMedia)]
    assert edit.media.media == "f1"
    assert len(harness.sent_messages) == cards_before
    assert harness.button_texts() == [BACK]


async def test_a_refused_file_id_falls_back_when_editing_the_card_into_the_photo(harness):
    await parsed(harness)
    harness.session.rejected_file_ids.add("f1")

    await harness.tap(USER, PHOTO)

    first, second = [c for c in harness.session.calls if isinstance(c, EditMessageMedia)]
    assert first.media.media == "f1"
    assert isinstance(second.media.media, BufferedInputFile)
    assert second.media.media.data == BYTES
    assert harness.button_texts() == [BACK]


async def test_a_missing_file_shows_the_notice_instead_of_the_photo(harness, tmp_storage):
    first_id, photo_data = await older_card_photo_data(harness)
    harness.session.rejected_file_ids.add("f1")
    for path in tmp_storage._root.rglob("*.jpg"):
        path.unlink()

    await harness.press(USER, photo_data, first_id)

    assert harness.sent_messages[-1].text == i18n.get("card-photo-unavailable")
    assert [p.photo for p in harness.sent_photos] == ["f1"]  # the refused attempt only
    assert harness.button_texts() == [BACK]


async def test_a_missing_file_shows_the_notice_when_editing_the_card(harness, tmp_storage):
    await parsed(harness)
    harness.session.rejected_file_ids.add("f1")
    for path in tmp_storage._root.rglob("*.jpg"):
        path.unlink()

    await harness.tap(USER, PHOTO)

    assert harness.sent_messages[-1].text == i18n.get("card-photo-unavailable")
    assert harness.button_texts() == [BACK]
    await harness.tap(USER, BACK)
    assert harness.button_texts() == [ITEMS, REVIEW, CATEGORY, PHOTO, DELETE, REPARSE, CLOSE]
