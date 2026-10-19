"""The manual entry expires: tracked by the dialog message manager, closed with its message."""

import pytest

from src.bot.screens import Screen, ScreenKind
from tests.bot.test_expense_entry import (
    CASH,
    PHOTO_PROMPT,
    SKIP,
    USER,
    expenses,
    to_category,
    to_source,
)


@pytest.fixture(autouse=True)
async def _allowed(allow_user):
    await allow_user(USER)


async def start_entry(harness) -> int:
    await harness.send_text("12.50", user_id=USER)
    return harness.session.sent_ids[-1]


async def test_an_entry_prompt_is_deleted_31_minutes_after_the_last_step_and_not_29(harness):
    prompt = await start_entry(harness)

    await harness.sweep(after_minutes=29)
    assert harness.deleted_messages == []

    await harness.sweep(after_minutes=2)
    assert harness.deleted_messages == [prompt]


async def test_a_step_at_minute_20_extends_the_entry(harness):
    prompt = await start_entry(harness)
    await harness.sweep(after_minutes=20)
    await harness.tap(USER, "✏️ Type a name")

    await harness.sweep(after_minutes=29)
    assert harness.deleted_messages == []

    await harness.sweep(after_minutes=2)
    assert harness.deleted_messages == [prompt]


async def test_a_typed_step_extends_the_entry_too(harness):
    await start_entry(harness)
    await harness.tap(USER, "✏️ Type a name")
    await harness.sweep(after_minutes=20)
    await harness.send_text("Mercadona", user_id=USER)

    await harness.sweep(after_minutes=29)

    assert harness.deleted_messages == []


async def test_after_the_sweep_the_entry_is_closed(harness, session_factory):
    await to_category(harness)
    await harness.sweep(after_minutes=31)

    await harness.send_text("hello", user_id=USER)
    assert harness.last_text() == PHOTO_PROMPT

    await harness.send_text("7", user_id=USER)
    assert harness.last_text().startswith("<b>7.00 €</b>")
    assert await expenses(session_factory) == []


async def test_a_word_typed_in_a_text_step_is_not_swallowed_after_the_sweep(harness):
    await start_entry(harness)
    await harness.tap(USER, "✏️ Type a name")
    await harness.sweep(after_minutes=31)

    await harness.send_text("Mercadona", user_id=USER)

    assert harness.last_text() == PHOTO_PROMPT


async def test_a_finished_entry_and_its_card_survive_every_sweep(harness, session_factory):
    await to_source(harness)
    await harness.tap(USER, CASH)
    await harness.tap(USER, "Groceries")
    await harness.tap(USER, "Today")
    await harness.tap(USER, SKIP)
    assert len(await expenses(session_factory)) == 1

    await harness.sweep(after_minutes=600)

    assert harness.deleted_messages == []


async def test_a_restarted_entry_is_swept_like_any_entry(harness):
    """A number typed in a choice step restarts the entry: only the new prompt is swept."""
    await to_category(harness)
    await harness.send_text("3", user_id=USER)
    fresh = harness.session.sent_ids[-1]

    await harness.sweep(after_minutes=31)

    assert fresh in harness.deleted_messages


async def test_cards_are_never_tracked(harness):
    await harness.send_photo(user_id=USER, data=b"jpeg")
    await harness.tasks.drain()

    await harness.sweep(after_minutes=600)

    assert harness.deleted_messages == []


async def test_sweeping_an_entry_with_no_open_dialog_only_deletes_the_message(harness, caplog):
    await harness.screens.track(Screen(USER, 501, ScreenKind.ENTRY))

    await harness.sweep(after_minutes=31)

    assert harness.deleted_messages == [501]
    assert not caplog.records


async def test_an_old_entry_prompt_is_deleted_but_does_not_close_the_card_that_replaced_it(
    harness,
):
    prompt = await start_entry(harness)
    await harness.send_photo(user_id=USER, data=b"jpeg")
    await harness.tasks.drain()

    await harness.sweep(after_minutes=31)
    assert prompt in harness.deleted_messages

    await harness.send_text("hello", user_id=USER)
    assert harness.last_text() == PHOTO_PROMPT  # the card stays untouched either way
