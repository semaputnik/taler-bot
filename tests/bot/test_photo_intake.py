"""Photo intake through the real dispatcher: stubbed Telegram, stub parser, real Postgres."""

import re

import pytest
from sqlalchemy import text

from src.bot.i18n import DEFAULT_LOCALE, create_translator_hub
from src.integration.llm import LLMError
from tests.stubs import fixture, output_of

USER = 7
TOO_LARGE = 20 * 1024 * 1024 + 1

i18n = create_translator_hub().get_translator_by_locale(DEFAULT_LOCALE)


@pytest.fixture(autouse=True)
async def _allowed(allow_user):
    await allow_user(USER)


def replied_to(sent) -> int | None:
    return sent.reply_parameters.message_id if sent.reply_parameters else None


async def statuses(session_factory) -> list[str]:
    async with session_factory() as session:
        rows = await session.execute(text("select status from receipts order by id"))
        return [row[0] for row in rows]


async def test_a_photo_is_saved_with_a_reply_then_the_card_is_sent(harness):
    message_id = await harness.send_photo(user_id=USER)
    await harness.tasks.drain()

    saved, summary = harness.sent_messages
    assert saved.text == i18n.get("receipt-saved")
    assert replied_to(saved) == message_id  # the card is a dialog message: no reply-to
    assert "Consum" in summary.text
    assert "Total: <b>7.58 €</b>" in summary.text
    assert "card VISA •0848" in summary.text
    assert "Items: 2" in summary.text
    assert "⚠️" not in summary.text  # issues are reviewed from the button, not listed
    assert re.search(r"\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}", summary.text)


async def test_the_largest_photo_size_is_downloaded(harness):
    await harness.send_photo(user_id=USER, file_id="big")
    await harness.tasks.drain()

    assert [call.file_id for call in harness.get_file_calls] == ["big"]


async def test_an_image_document_is_handled_like_a_photo(harness):
    await harness.send_document(user_id=USER, mime_type="image/png")
    await harness.tasks.drain()

    saved, summary = harness.sent_messages
    assert saved.text == i18n.get("receipt-saved")
    assert "Consum" in summary.text


@pytest.mark.parametrize("mime_type", ["application/pdf", None])
async def test_a_non_image_document_is_asked_for_a_photo(harness, mime_type):
    await harness.send_document(user_id=USER, mime_type=mime_type)

    (sent,) = harness.sent_messages
    assert sent.text == i18n.get("photo-send-me-one")
    assert harness.get_file_calls == []


async def test_plain_text_is_asked_for_a_photo(harness):
    await harness.send_text("hello", user_id=USER)

    (sent,) = harness.sent_messages
    assert sent.text == i18n.get("photo-send-me-one")


async def test_start_still_greets(harness):
    await harness.send_text("/start", user_id=USER)

    (sent,) = harness.sent_messages
    assert "Ann" in sent.text


async def test_a_document_over_20_mb_is_refused_without_a_download(harness):
    await harness.send_document(user_id=USER, mime_type="image/jpeg", file_size=TOO_LARGE)

    (sent,) = harness.sent_messages
    assert sent.text == i18n.get("photo-too-large")
    assert harness.get_file_calls == []


async def test_the_same_photo_twice_is_refused_the_second_time(harness, session_factory):
    await harness.send_photo(user_id=USER, unique_id="same")
    await harness.tasks.drain()
    await harness.send_photo(user_id=USER, file_id="f2", unique_id="same")
    await harness.tasks.drain()

    assert harness.sent_messages[-1].text == i18n.get("photo-already-have")
    assert len(harness.sent_messages) == 3
    assert await statuses(session_factory) == ["parsed"]


async def test_not_a_receipt_is_reported(harness, session_factory):
    raw = fixture("03")["raw"] | {"is_receipt": False, "items": [], "issues": []}
    harness.parser.default = output_of(raw)

    await harness.send_photo(user_id=USER)
    await harness.tasks.drain()

    assert harness.sent_messages[-1].text.startswith(i18n.get("receipt-not-a-receipt"))
    assert await statuses(session_factory) == ["not_receipt"]


async def test_a_model_failure_is_reported_and_the_receipt_is_failed(harness, session_factory):
    harness.parser.error = LLMError("timed out")

    message_id = await harness.send_photo(user_id=USER)
    await harness.tasks.drain()

    saved, failed = harness.sent_messages
    assert failed.text.startswith(i18n.get("receipt-failed"))
    assert failed.reply_markup is not None
    assert replied_to(saved) == message_id
    assert await statuses(session_factory) == ["failed"]


async def test_an_unexpected_error_still_tells_the_user_once(harness, session_factory):
    harness.parser.error = RuntimeError("bug")

    await harness.send_photo(user_id=USER)
    await harness.tasks.drain()

    saved, failed = harness.sent_messages
    assert saved.text == i18n.get("receipt-saved")
    assert failed.text.startswith(i18n.get("receipt-failed"))
    assert await statuses(session_factory) == ["failed"]


async def test_the_same_receipt_photographed_twice_names_the_original(harness, session_factory):
    await harness.send_photo(user_id=USER, file_id="a")
    await harness.tasks.drain()
    await harness.send_photo(user_id=USER, file_id="b")
    await harness.tasks.drain()

    duplicate = harness.sent_messages[-1]
    assert duplicate.text.startswith("♻️")
    assert "Consum" in duplicate.text
    assert "7.58 €" in duplicate.text
    assert await statuses(session_factory) == ["parsed", "duplicate"]


async def test_the_saved_reply_is_sent_before_the_parser_is_called(harness):
    seen: list[int] = []
    original = harness.parser.parse

    async def parse(image, media_type):
        seen.append(len(harness.sent_messages))  # replies sent when the model is called
        return await original(image, media_type)

    harness.parser.parse = parse

    await harness.send_photo(user_id=USER)
    await harness.tasks.drain()

    assert seen == [1]


async def test_model_text_is_html_escaped_in_the_summary(harness):
    raw = fixture("03")["raw"]
    raw = raw | {"store": raw["store"] | {"name": "<b>Shop & Co"}}
    harness.parser.default = output_of(raw)

    await harness.send_photo(user_id=USER)
    await harness.tasks.drain()

    assert "&lt;b&gt;Shop &amp; Co" in harness.sent_messages[-1].text


async def test_a_sticker_is_asked_for_a_photo(harness):
    from aiogram.types import Sticker

    await harness._feed(
        USER,
        sticker=Sticker(
            file_id="s",
            file_unique_id="s",
            type="regular",
            width=1,
            height=1,
            is_animated=False,
            is_video=False,
        ),
    )

    (sent,) = harness.sent_messages
    assert sent.text == i18n.get("photo-send-me-one")


async def test_typing_is_shown_while_the_photo_is_read_and_ends_before_the_summary(
    harness, monkeypatch
):
    monkeypatch.setattr("src.bot.handlers.message.photo.TYPING_INTERVAL", 0.01)
    harness.parser.delay = 0.1

    await harness.send_photo(user_id=USER)
    await harness.tasks.drain()

    calls = harness.session.calls
    saved = next(i for i, call in enumerate(calls) if call is harness.sent_messages[0])
    summary = next(i for i, call in enumerate(calls) if call is harness.sent_messages[-1])
    typing = [i for i, call in enumerate(calls) if call in harness.chat_actions]
    assert len(typing) >= 2  # repeated while the model works
    assert all(saved < i < summary for i in typing)
    assert all(call.action == "typing" and call.chat_id == USER for call in harness.chat_actions)


async def test_a_failing_chat_action_does_not_affect_the_summary(harness):
    harness.session.chat_action_fails = True

    await harness.send_photo(user_id=USER)
    await harness.tasks.drain()

    saved, summary = harness.sent_messages
    assert "Consum" in summary.text
