"""The /reparse command and its bulk buttons through the real dispatcher on real Postgres."""

import asyncio

import pytest
from aiogram.methods import AnswerCallbackQuery, EditMessageText
from sqlalchemy import text

from src.bot.i18n import DEFAULT_LOCALE, create_translator_hub
from src.domain.normalize import PARSER_VERSION
from src.integration.llm import LLMError
from tests.stubs import fixture, output_of

USER = 7

i18n = create_translator_hub().get_translator_by_locale(DEFAULT_LOCALE)
FAILED_BUTTON = "🔁 Re-parse failed ({})"
OUTDATED_BUTTON = "🔁 Re-parse outdated ({})"


@pytest.fixture(autouse=True)
async def _allowed(allow_user):
    await allow_user(USER)


async def read(harness, file_id: str, *, fail: bool = False) -> None:
    harness.parser.error = LLMError("timed out") if fail else None
    await harness.send_photo(user_id=USER, file_id=file_id)
    await harness.tasks.drain()
    harness.parser.error = None


async def make_outdated(session_factory) -> None:
    async with session_factory() as session:
        await session.execute(text("update receipt_parses set parser_version = 'old'"))
        await session.commit()


async def versions(session_factory) -> list[str]:
    async with session_factory() as session:
        rows = await session.execute(text("select parser_version from receipt_parses"))
        return [row[0] for row in rows]


def summary(failed: int, outdated: int) -> str:
    return i18n.get("reparse-summary", failed=failed, outdated=outdated, version=PARSER_VERSION)


async def test_it_shows_the_counts_and_both_buttons(harness, session_factory):
    await read(harness, "a")
    await read(harness, "b", fail=True)
    await make_outdated(session_factory)

    await harness.send_text("/reparse", user_id=USER)

    assert harness.last_text() == summary(1, 1)
    assert harness.button_texts() == [FAILED_BUTTON.format(1), OUTDATED_BUTTON.format(1)]


async def test_only_the_button_with_a_count_is_shown(harness, session_factory):
    await read(harness, "a")
    await make_outdated(session_factory)

    await harness.send_text("/reparse", user_id=USER)

    assert harness.last_text() == summary(0, 1)
    assert harness.button_texts() == [OUTDATED_BUTTON.format(1)]


async def test_nothing_to_do_has_the_text_and_no_buttons(harness):
    await read(harness, "a")
    keyboards_before = len(harness.keyboards())

    await harness.send_text("/reparse", user_id=USER)

    assert harness.last_text() == i18n.get("reparse-none")
    assert len(harness.keyboards()) == keyboards_before


async def test_a_stranger_gets_no_reply(harness):
    await harness.send_text("/reparse", user_id=999)

    assert harness.session.calls == []


async def test_a_tap_edits_the_message_runs_the_receipts_and_reports(harness, session_factory):
    for file_id, name in [("a", "03"), ("b", "04"), ("c", "07")]:
        harness.parser.outputs[file_id.encode()] = output_of(fixture(name)["raw"])
        await read(harness, file_id)
    await make_outdated(session_factory)
    await harness.send_text("/reparse", user_id=USER)
    command_reply = harness.last_keyboard()[0]
    harness.parser.error = None
    calls_before = len(harness.session.calls)

    await harness.tap(USER, OUTDATED_BUTTON.format(3))
    await harness.tasks.drain()

    new_calls = harness.session.calls[calls_before:]
    assert isinstance(new_calls[0], AnswerCallbackQuery)
    edit = next(c for c in new_calls if isinstance(c, EditMessageText))
    assert edit.text == i18n.get("reparse-progress", count=3)
    assert edit.message_id == command_reply and edit.reply_markup is None
    done = harness.sent_messages[-1]
    assert done.text == i18n.get("reparse-done", total=3, ok=3, failed=0)
    assert done.reply_parameters.message_id == command_reply
    assert await versions(session_factory) == [PARSER_VERSION] * 3


async def test_the_summary_counts_the_receipts_that_failed_again(harness):
    await read(harness, "a", fail=True)
    await read(harness, "b", fail=True)
    await harness.send_text("/reparse", user_id=USER)
    harness.parser.outputs[b"a"] = output_of(fixture("04")["raw"])
    harness.parser.error = None
    harness.parser.gates[b"b"] = gate = asyncio.Event()
    harness.parser.events.clear()

    await harness.tap(USER, FAILED_BUTTON.format(2))
    while ("start", b"b") not in harness.parser.events:  # noqa: ASYNC110 - "a" is read, "b" waits
        await asyncio.sleep(0.01)
    harness.parser.error = LLMError("down")
    gate.set()
    await harness.tasks.drain()

    assert harness.sent_messages[-1].text == i18n.get("reparse-done", total=2, ok=1, failed=1)


async def test_the_typing_status_runs_during_the_bulk_read(harness, session_factory, monkeypatch):
    monkeypatch.setattr("src.bot.handlers.callback.reparse.TYPING_INTERVAL", 0.01)
    await read(harness, "a")
    await make_outdated(session_factory)
    await harness.send_text("/reparse", user_id=USER)
    harness.parser.delay = 0.1
    actions_before = len(harness.chat_actions)

    await harness.tap(USER, OUTDATED_BUTTON.format(1))
    await harness.tasks.drain()

    assert len(harness.chat_actions) - actions_before >= 2


async def test_a_second_tap_during_a_slow_run_alerts(harness, session_factory):
    await read(harness, "a")
    await make_outdated(session_factory)
    await harness.send_text("/reparse", user_id=USER)
    message_id, markup = harness.last_keyboard()
    data = markup.inline_keyboard[0][0].callback_data
    harness.parser.gates[b"a"] = gate = asyncio.Event()
    harness.parser.started = asyncio.Event()
    await harness.tap(USER, OUTDATED_BUTTON.format(1))
    await harness.parser.started.wait()
    starts = len([e for e in harness.parser.events if e[0] == "start"])

    await harness.press(USER, data, message_id)

    alert = harness.session.calls[-1]
    assert isinstance(alert, AnswerCallbackQuery)
    assert (alert.text, alert.show_alert) == (i18n.get("reparse-running"), True)
    gate.set()
    await harness.tasks.drain()
    assert len([e for e in harness.parser.events if e[0] == "start"]) == starts
    assert len([m for m in harness.sent_messages if "Re-parsed" in m.text]) == 1


async def test_a_tap_after_the_run_ended_is_not_blocked_and_finds_nothing_left(
    harness, session_factory
):
    await read(harness, "a", fail=True)
    await harness.send_text("/reparse", user_id=USER)
    message_id, markup = harness.last_keyboard()
    data = markup.inline_keyboard[0][0].callback_data
    await harness.tap(USER, FAILED_BUTTON.format(1))
    await harness.tasks.drain()

    await harness.press(USER, data, message_id)  # a stale button: nothing is left to read
    await harness.tasks.drain()

    assert harness.sent_messages[-1].text == i18n.get("reparse-done", total=0, ok=0, failed=0)
