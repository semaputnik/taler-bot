"""Expiring plain screens (/expenses, /stats, /reparse): when a sweep deletes them."""

import pytest

from src.integration.llm import LLMError
from tests.bot.test_history import bought, failed

USER = 7
EXPENSES = "💸 Expenses"
SPENDING = "📊 Spending"
WEEK = "📅 Week"
FAILED_BUTTON = "🔁 Re-parse failed (1)"


@pytest.fixture(autouse=True)
async def _allowed(allow_user):
    await allow_user(USER)


def last_sent_id(harness) -> int:
    return harness.session.sent_ids[-1]


async def assert_expires(harness, message_id: int) -> None:
    await harness.sweep(after_minutes=29)
    assert message_id not in harness.deleted_messages
    await harness.sweep(after_minutes=2)
    assert message_id in harness.deleted_messages


async def test_expenses_expires(harness):
    await harness.send_text("/expenses", user_id=USER)

    await assert_expires(harness, last_sent_id(harness))


async def test_stats_expires(harness):
    await harness.send_text("/stats", user_id=USER)

    await assert_expires(harness, last_sent_id(harness))


async def test_reparse_question_expires(harness):
    harness.parser.error = LLMError("timed out")
    await harness.send_photo(user_id=USER)
    await harness.tasks.drain()
    await harness.send_text("/reparse", user_id=USER)

    await assert_expires(harness, last_sent_id(harness))


async def test_history_opened_from_start_expires(harness):
    await harness.send_text("/start", user_id=USER)
    await harness.tap(USER, EXPENSES)

    await assert_expires(harness, last_sent_id(harness))


async def test_stats_opened_from_start_expires(harness):
    await harness.send_text("/start", user_id=USER)
    await harness.tap(USER, SPENDING)

    await assert_expires(harness, last_sent_id(harness))


async def test_history_opened_from_the_stats_month_button_expires(harness, make_uow):
    await bought(make_uow, 5)
    await harness.send_text("/stats", user_id=USER)
    await harness.tap(USER, EXPENSES)

    await assert_expires(harness, last_sent_id(harness))


async def test_a_history_tap_extends_the_time(harness, make_uow):
    await bought(make_uow, 5)
    await harness.send_text("/expenses", user_id=USER)
    message_id = last_sent_id(harness)
    harness.clock.advance(minutes=20)
    await harness.tap(USER, "Payee ▾")

    await harness.sweep(after_minutes=11)
    assert message_id not in harness.deleted_messages
    await harness.sweep(after_minutes=20)
    assert message_id in harness.deleted_messages


async def test_a_stats_tap_extends_the_time(harness):
    await harness.send_text("/stats", user_id=USER)
    message_id = last_sent_id(harness)
    harness.clock.advance(minutes=20)
    await harness.tap(USER, WEEK)

    await harness.sweep(after_minutes=11)
    assert message_id not in harness.deleted_messages
    await harness.sweep(after_minutes=20)
    assert message_id in harness.deleted_messages


async def test_confirming_a_reparse_forgets_the_question_and_keeps_the_rest(harness):
    harness.parser.error = LLMError("timed out")
    await harness.send_photo(user_id=USER)
    await harness.tasks.drain()
    await harness.send_text("/reparse", user_id=USER)
    question = last_sent_id(harness)

    await harness.tap(USER, FAILED_BUTTON)
    await harness.tasks.drain()
    await harness.sweep(after_minutes=600)

    assert harness.deleted_messages == []
    assert question in harness.session.sent_ids


async def test_cards_hints_and_errors_are_never_tracked(harness, make_uow):
    harness.parser.error = LLMError("timed out")
    await harness.send_photo(user_id=USER)  # "Saved, reading…" and the error card
    await harness.tasks.drain()
    await harness.send_text("hello", user_id=USER)  # the "send me a photo" hint
    await failed(make_uow, 3)

    await harness.sweep(after_minutes=600)

    assert harness.deleted_messages == []
