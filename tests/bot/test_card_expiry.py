"""Cards expire unless the bot sent them by itself (after a parse or an entry)."""

import pytest

from tests.bot.test_expense_card import AMOUNT, BACK, CLOSE, PAYEE, entered
from tests.bot.test_history import bought
from tests.helpers import add_manual_expense

USER = 7


@pytest.fixture(autouse=True)
async def _allowed(allow_user):
    await allow_user(USER)


async def open_from_history(harness) -> int:
    await harness.send_text("/expenses", user_id=USER)
    await harness.tap(USER, harness.button_texts()[0])
    return harness.session.sent_ids[-1]


async def test_a_card_opened_from_a_history_row_is_deleted_at_31_minutes_not_29(harness, make_uow):
    await add_manual_expense(make_uow, USER)
    card = await open_from_history(harness)

    await harness.sweep(after_minutes=29)
    assert card not in harness.deleted_messages

    await harness.sweep(after_minutes=2)
    assert card in harness.deleted_messages


async def test_a_receipt_card_opened_from_a_history_row_expires_too(harness, make_uow):
    await bought(make_uow, 14)
    card = await open_from_history(harness)

    await harness.sweep(after_minutes=31)

    assert card in harness.deleted_messages


async def test_a_copy_from_an_older_card_expires_and_the_original_stays(harness):
    original = await entered(harness)
    _, markup = harness.last_keyboard()
    await harness.send_text("3", user_id=USER)  # a newer message: the original is now "older"

    data = next(b.callback_data for r in markup.inline_keyboard for b in r if b.text == AMOUNT)
    await harness.press(USER, data, original)
    copy = harness.session.sent_ids[-1]
    assert copy != original

    await harness.sweep(after_minutes=31)

    assert copy in harness.deleted_messages
    assert original not in harness.deleted_messages


async def test_the_receipt_card_after_a_photo_and_the_card_after_an_entry_stay(harness):
    await harness.send_photo(user_id=USER)
    await harness.tasks.drain()
    await entered(harness)

    await harness.sweep(after_minutes=600)

    assert harness.deleted_messages == []


async def test_a_window_opened_on_a_tracked_card_extends_it(harness, make_uow):
    await add_manual_expense(make_uow, USER)
    card = await open_from_history(harness)
    await harness.sweep(after_minutes=20)
    await harness.tap(USER, PAYEE)

    await harness.sweep(after_minutes=11)
    assert card not in harness.deleted_messages

    await harness.sweep(after_minutes=20)
    assert card in harness.deleted_messages


async def test_back_and_close_keep_a_tracked_card_tracked(harness, make_uow):
    await add_manual_expense(make_uow, USER)
    card = await open_from_history(harness)
    await harness.tap(USER, PAYEE)
    await harness.tap(USER, BACK)
    await harness.tap(USER, CLOSE)

    await harness.sweep(after_minutes=31)

    assert card in harness.deleted_messages


async def test_a_tracked_card_that_becomes_a_photo_message_still_expires(harness, make_uow):
    await bought(make_uow, 14)
    await open_from_history(harness)
    await harness.tap(USER, "🖼 Photo")
    shown = harness.session.sent_ids[-1]

    await harness.sweep(after_minutes=31)

    assert shown in harness.deleted_messages
