"""The card's Re-parse button through the real dispatcher on real Postgres."""

import pytest
from aiogram.methods import AnswerCallbackQuery, EditMessageReplyMarkup
from sqlalchemy import text

from src.bot.i18n import DEFAULT_LOCALE, create_translator_hub
from src.integration.llm import LLMError
from tests.stubs import fixture, output_of

USER = 7
REPARSE = "🔄 Re-parse"
CONFIRM = "🔄 Yes, read again"
PHOTO = "🖼 Photo"

i18n = create_translator_hub().get_translator_by_locale(DEFAULT_LOCALE)


@pytest.fixture(autouse=True)
async def _allowed(allow_user):
    await allow_user(USER)


async def parsed(harness, **kwargs) -> int:
    await harness.send_photo(user_id=USER, **kwargs)
    await harness.tasks.drain()
    return harness.last_keyboard()[0]


async def statuses(session_factory) -> list[str]:
    async with session_factory() as session:
        rows = await session.execute(text("select status from receipts order by id"))
        return [row[0] for row in rows]


def total_of(card_text: str) -> str:
    return next(line for line in card_text.splitlines() if "€" in line)


async def test_the_button_is_on_a_parsed_card_before_close(harness):
    await parsed(harness)

    texts = harness.button_texts()
    assert REPARSE in texts
    assert texts[-2:] == [REPARSE, "✖ Close"]
    assert [b.text for b in harness.last_keyboard()[1].inline_keyboard[-2]] == ["✏️ Edit", REPARSE]


async def test_the_button_is_on_a_failed_card(harness):
    harness.parser.error = LLMError("timed out")

    await parsed(harness)

    assert REPARSE in harness.button_texts()


async def test_the_button_is_not_on_a_duplicate_card(harness):
    await parsed(harness, file_id="a")
    await parsed(harness, file_id="b")

    assert REPARSE not in harness.button_texts()


async def test_a_tap_replies_reading_again_then_sends_a_fresh_card(harness, monkeypatch):
    monkeypatch.setattr("src.bot.handlers.parse_task.TYPING_INTERVAL", 0.01)
    card_id = await parsed(harness)
    old_markup = harness.last_keyboard()[1]
    harness.parser.default = output_of(fixture("04")["raw"])
    harness.parser.delay = 0.1
    calls_before = len(harness.session.calls)

    await harness.tap(USER, REPARSE)
    await harness.tap(USER, CONFIRM)
    await harness.tasks.drain()

    new_calls = harness.session.calls[calls_before:]
    started, card = [m for m in new_calls if m in harness.sent_messages]
    assert started.text == i18n.get("reparse-started")
    assert started.reply_parameters.message_id == card_id
    assert "Ametller" in card.text
    assert isinstance(new_calls[0], AnswerCallbackQuery)
    typing = [c for c in new_calls if c in harness.chat_actions]
    assert len(typing) >= 2
    assert new_calls.index(started) < new_calls.index(typing[0])
    assert new_calls.index(typing[-1]) < new_calls.index(card)
    # The old card keeps its buttons, the fresh one has its own.
    assert not [c for c in new_calls if isinstance(c, EditMessageReplyMarkup)]
    assert harness.keyboards()[-1][0] != card_id
    assert old_markup in [m for mid, m in harness.keyboards() if mid == card_id]
    assert REPARSE in harness.button_texts()


async def test_a_failed_reread_keeps_the_reading_and_the_card_shows_the_error(
    harness, session_factory
):
    await parsed(harness)
    first_total = total_of(harness.last_text())
    harness.parser.error = LLMError("timed out")

    await harness.tap(USER, REPARSE)
    await harness.tap(USER, CONFIRM)
    await harness.tasks.drain()

    card = harness.last_text()
    assert total_of(card) == first_total  # the old reading
    assert i18n.get("card-error", reason="timed out") in card
    assert await statuses(session_factory) == ["parsed"]
    assert REPARSE in harness.button_texts()


async def test_a_failed_card_shows_the_error_line(harness):
    harness.parser.error = LLMError("timed out")

    await parsed(harness)

    assert i18n.get("card-error", reason="timed out") in harness.last_text()


async def test_a_stale_button_on_a_receipt_that_became_a_duplicate_alerts(harness, session_factory):
    await parsed(harness, file_id="a")
    harness.parser.default = output_of(fixture("04")["raw"])
    second_id = await parsed(harness, file_id="b")
    stale = harness.last_keyboard()[1].inline_keyboard[-2][-1].callback_data
    harness.parser.default = output_of(fixture("03")["raw"])
    await harness.tap(USER, REPARSE)  # the second receipt now repeats the first
    await harness.tap(USER, CONFIRM)
    await harness.tasks.drain()
    assert await statuses(session_factory) == ["parsed", "duplicate"]
    sent_before = len(harness.sent_messages)

    await harness.press(USER, stale, second_id)

    alert = harness.session.calls[-1]
    assert isinstance(alert, AnswerCallbackQuery)
    assert (alert.text, alert.show_alert) == (i18n.get("reparse-not-possible"), True)
    assert len(harness.sent_messages) == sent_before
    assert harness.parser.events[-1][0] == "end"
    assert len([e for e in harness.parser.events if e[0] == "start"]) == 3


async def test_reparse_asks_for_a_confirmation_and_back_reads_nothing(harness):
    await parsed(harness)
    starts_before = len([e for e in harness.parser.events if e[0] == "start"])

    await harness.tap(USER, REPARSE)
    assert harness.last_text() == i18n.get("card-reparse-confirm")
    assert harness.button_texts() == [CONFIRM, "◀ Back"]

    await harness.tap(USER, "◀ Back")
    await harness.tasks.drain()

    assert REPARSE in harness.button_texts()
    assert len([e for e in harness.parser.events if e[0] == "start"]) == starts_before
