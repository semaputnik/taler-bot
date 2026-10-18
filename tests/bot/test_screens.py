"""Expiring screens, seen through the dispatcher: what Telegram is asked to delete, and when."""

import logging

from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import DeleteMessage, EditMessageReplyMarkup

from src.bot.screens import Screen, ScreenKind


async def test_the_start_greeting_is_deleted_by_a_sweep_31_minutes_later(harness, allow_user):
    await allow_user(7)
    await harness.send_text("/start", user_id=7)
    (greeting,) = harness.session.sent_ids

    await harness.sweep(after_minutes=29)
    assert harness.deleted_messages == []

    await harness.sweep(after_minutes=2)
    assert harness.deleted_messages == [greeting]
    (deletion,) = [c for c in harness.session.calls if isinstance(c, DeleteMessage)]
    assert deletion.chat_id == 7


async def test_a_swept_screen_is_not_swept_twice(harness, allow_user):
    await allow_user(7)
    await harness.send_text("/start", user_id=7)

    await harness.sweep(after_minutes=31)
    await harness.sweep(after_minutes=31)

    assert len(harness.deleted_messages) == 1


async def test_a_refused_delete_falls_back_to_removing_the_keyboard(
    harness, allow_user, monkeypatch
):
    await allow_user(7)
    await harness.send_text("/start", user_id=7)
    (greeting,) = harness.session.sent_ids
    original = harness.session.make_request

    async def refuse_delete(bot, method, **kwargs):
        if isinstance(method, DeleteMessage):
            raise TelegramBadRequest(method=method, message="message can't be deleted")
        return await original(bot, method, **kwargs)

    monkeypatch.setattr(harness.session, "make_request", refuse_delete)

    await harness.sweep(after_minutes=31)

    (edit,) = [c for c in harness.session.calls if isinstance(c, EditMessageReplyMarkup)]
    assert (edit.chat_id, edit.message_id, edit.reply_markup) == (7, greeting, None)


async def test_two_refusals_are_logged_at_warning_and_the_sweep_goes_on(
    harness, monkeypatch, caplog
):
    first = Screen(1, 501, ScreenKind.PLAIN)
    second = Screen(1, 502, ScreenKind.PLAIN)
    await harness.screens.track(first)
    harness.clock.advance(minutes=1)
    await harness.screens.track(second)
    original = harness.session.make_request

    async def refuse_everything_for_the_first(bot, method, **kwargs):
        if isinstance(method, DeleteMessage | EditMessageReplyMarkup) and (
            method.message_id == first.message_id
        ):
            raise TelegramBadRequest(method=method, message="message to delete not found")
        return await original(bot, method, **kwargs)

    monkeypatch.setattr(harness.session, "make_request", refuse_everything_for_the_first)

    with caplog.at_level(logging.WARNING):
        await harness.sweep(after_minutes=31)

    assert harness.deleted_messages == [second.message_id]
    assert any(r.levelno == logging.WARNING and "501" in r.getMessage() for r in caplog.records)


async def test_the_sweeper_survives_a_sweep_that_raises(harness, monkeypatch, caplog):
    import asyncio

    from src.bot.sweeper import ScreenSweeper

    calls = []
    twice = asyncio.Event()

    async def due(now):
        calls.append(now)
        if len(calls) == 2:
            twice.set()
        if len(calls) == 1:
            raise RuntimeError("redis is down")
        return []

    monkeypatch.setattr(harness.screens, "due", due)
    sweeper = ScreenSweeper(harness.bot, harness.screens, interval_seconds=0.01)
    task = asyncio.create_task(sweeper.run())
    with caplog.at_level(logging.ERROR):
        await asyncio.wait_for(twice.wait(), 5)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert len(calls) >= 2
    assert any("Screen sweep failed" in r.getMessage() for r in caplog.records)


async def test_a_receipt_card_and_saved_replies_are_never_tracked(harness, allow_user):
    await allow_user(7)
    await harness.send_photo(user_id=7)
    await harness.tasks.drain()

    await harness.sweep(after_minutes=600)

    assert harness.deleted_messages == []
