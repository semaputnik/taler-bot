"""The ReceiptCard dialog (delete flow) through the real dispatcher on real Postgres."""

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import AnswerCallbackQuery, EditMessageReplyMarkup, EditMessageText
from sqlalchemy import text

from src.bot.i18n import DEFAULT_LOCALE, create_translator_hub
from src.integration.llm import LLMError
from tests.stubs import fixture, output_of

USER = 7
DELETE = "🗑 Delete"

i18n = create_translator_hub().get_translator_by_locale(DEFAULT_LOCALE)


@pytest.fixture(autouse=True)
async def _allowed(allow_user):
    await allow_user(USER)


async def deleted_flags(session_factory) -> list[bool]:
    async with session_factory() as session:
        rows = await session.execute(
            text("select deleted_at is not null from receipts order by id")
        )
        return [row[0] for row in rows]


def stored_files(storage) -> list[str]:
    root = storage._root
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


async def parsed(harness, **kwargs) -> int:
    """Send a photo, wait for the reply; return the summary's message id."""
    await harness.send_photo(user_id=USER, **kwargs)
    await harness.tasks.drain()
    return harness.last_keyboard()[0]


def last_text(harness) -> str:
    """The text of the latest message the dialog sent or edited."""
    for call in reversed(harness.session.calls):
        if isinstance(call, EditMessageText):
            return call.text
        if call in harness.sent_messages:
            return call.text
    raise AssertionError("nothing sent")


async def test_the_parse_reply_carries_a_delete_button(harness):
    await parsed(harness)

    assert harness.button_texts() == [DELETE]


@pytest.mark.parametrize("outcome", ["not_receipt", "failed"])
async def test_every_parse_outcome_carries_the_keyboard(harness, outcome):
    if outcome == "failed":
        harness.parser.error = LLMError("timed out")
    else:
        raw = fixture("03")["raw"] | {"is_receipt": False, "items": [], "issues": []}
        harness.parser.default = output_of(raw)

    await parsed(harness)

    assert harness.button_texts() == [DELETE]


async def test_the_duplicate_reply_carries_the_keyboard(harness):
    await parsed(harness, file_id="a")
    await parsed(harness, file_id="b")

    assert harness.sent_messages[-1].text.startswith("♻️")
    assert harness.button_texts() == [DELETE]


async def test_delete_opens_a_confirmation_as_a_new_message(harness):
    summary_id = await parsed(harness)
    sent_before = len(harness.sent_messages)

    await harness.tap(USER, DELETE)

    assert len(harness.sent_messages) == sent_before + 1
    assert harness.sent_messages[-1].text == i18n.get("card-delete-confirm")
    assert harness.button_texts() == ["🗑 Yes, delete", "◀ Back"]
    assert harness.last_keyboard()[0] != summary_id
    # the summary itself is never edited
    assert not [c for c in harness.session.calls if isinstance(c, EditMessageText)]


async def test_back_returns_to_the_card(harness):
    await parsed(harness)
    await harness.tap(USER, DELETE)

    await harness.tap(USER, "◀ Back")

    assert "Consum" in last_text(harness)
    assert harness.button_texts() == [DELETE, "✖ Close"]


async def test_confirming_deletes_the_receipt_and_trashes_the_photo(
    harness, session_factory, tmp_storage
):
    await parsed(harness)
    (path,) = stored_files(tmp_storage)
    await harness.tap(USER, DELETE)

    await harness.tap(USER, "🗑 Yes, delete")

    assert await deleted_flags(session_factory) == [True]
    assert stored_files(tmp_storage) == [f".trash/{path}"]
    assert harness.sent_messages[-1].text == i18n.get("card-deleted-done")


async def test_close_ends_the_dialog_and_keeps_the_receipt(harness, session_factory):
    await parsed(harness)
    await harness.tap(USER, DELETE)
    await harness.tap(USER, "◀ Back")

    await harness.tap(USER, "✖ Close")

    assert harness.last_keyboard()[1].inline_keyboard == []
    assert await deleted_flags(session_factory) == [False]


async def test_an_old_button_of_a_deleted_receipt_alerts_and_loses_its_keyboard(harness):
    summary_id = await parsed(harness)
    summary_data = harness.last_keyboard()[1].inline_keyboard[0][0].callback_data
    await harness.tap(USER, DELETE)
    await harness.tap(USER, "🗑 Yes, delete")
    sent_before = len(harness.sent_messages)

    await harness.press(USER, summary_data, summary_id)

    alert = harness.session.calls[-2]
    assert isinstance(alert, AnswerCallbackQuery)
    assert (alert.text, alert.show_alert) == (i18n.get("card-deleted-alert"), True)
    removal = harness.session.calls[-1]
    assert isinstance(removal, EditMessageReplyMarkup)
    assert (removal.message_id, removal.reply_markup) == (summary_id, None)
    assert len(harness.sent_messages) == sent_before


async def test_a_vanished_summary_message_is_tolerated(harness, monkeypatch):
    summary_id = await parsed(harness)
    data = harness.last_keyboard()[1].inline_keyboard[0][0].callback_data
    await harness.tap(USER, DELETE)
    await harness.tap(USER, "🗑 Yes, delete")

    async def gone(*args, **kwargs):
        raise TelegramBadRequest(
            method=EditMessageReplyMarkup(chat_id=1, message_id=1),
            message="Bad Request: message to edit not found",
        )

    monkeypatch.setattr(harness.bot, "edit_message_reply_markup", gone)

    await harness.press(USER, data, summary_id)  # must not raise


async def test_a_stranger_is_dropped_silently(harness, session_factory):
    await parsed(harness)
    data = harness.last_keyboard()[1].inline_keyboard[0][0].callback_data
    calls_before = len(harness.session.calls)

    await harness.press(999, data, 5)

    assert len(harness.session.calls) == calls_before
    assert await deleted_flags(session_factory) == [False]


async def test_a_photo_sent_while_the_card_is_open_is_still_saved(harness, session_factory):
    await parsed(harness, file_id="a")
    await harness.tap(USER, DELETE)

    await harness.send_photo(user_id=USER, file_id="b")
    await harness.tasks.drain()

    assert [m.text for m in harness.sent_messages].count(i18n.get("receipt-saved")) == 2
    async with session_factory() as session:
        count = (await session.execute(text("select count(*) from receipts"))).scalar_one()
    assert count == 2


async def test_a_failed_receipt_card_shows_its_status(harness):
    harness.parser.error = LLMError("timed out")
    await parsed(harness)
    await harness.tap(USER, DELETE)

    await harness.tap(USER, "◀ Back")

    body = last_text(harness)
    assert i18n.get("card-status-failed") in body
    assert "Photo received:" in body


async def test_a_duplicate_card_names_the_receipt_it_repeats(harness):
    await parsed(harness, file_id="a")
    await parsed(harness, file_id="b")
    await harness.tap(USER, DELETE)

    await harness.tap(USER, "◀ Back")

    body = last_text(harness)
    assert i18n.get("card-status-duplicate") in body
    assert "Repeats <b>Consum" in body
    assert "7.58 EUR" in body


async def test_a_receipt_that_is_being_read_cannot_be_deleted(harness, session_factory):
    await parsed(harness)
    await harness.tap(USER, DELETE)
    # Leave the receipt the way a running parse would.
    async with session_factory() as session:
        await session.execute(text("update receipts set status = 'parsing'"))
        await session.commit()

    await harness.tap(USER, "🗑 Yes, delete")

    alerts = [c for c in harness.session.calls if isinstance(c, AnswerCallbackQuery) and c.text]
    assert [(a.text, a.show_alert) for a in alerts] == [
        (i18n.get("card-cannot-delete-parsing"), True)
    ]
    assert await deleted_flags(session_factory) == [False]
