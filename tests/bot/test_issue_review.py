"""The issue review walk (ReceiptCard `issue` and `review_done` windows), end to end."""

import pytest
from aiogram.methods import AnswerCallbackQuery, EditMessageReplyMarkup
from sqlalchemy import text

from src.bot.i18n import DEFAULT_LOCALE, create_translator_hub
from tests.stubs import fixture, output_of

USER = 7
ITEMS = "📋 Items"
PHOTO = "🖼 Photo"
DELETE = "🗑 Delete"
CORRECT = "✅ Correct"
ENTER = "✏️ Enter value"
SKIP = "⏭ Skip"
CLOSE = "✖ Close"
BACK = "◀ Back"

i18n = create_translator_hub().get_translator_by_locale(DEFAULT_LOCALE)


def issue(severity: str, field: str, message: str, item: str | None = None) -> dict:
    return {
        "type": "other",
        "severity": severity,
        "field": field,
        "item_name_raw": item,
        "message": message,
    }


# Walk order: the high one, then the medium ones in parse order. The low one is not shown.
TOTAL = issue("high", "totals.total", "The total looks too high.")
LINE = issue("medium", "items.line_total", "Line math is off.", "CERV FREE LIMO.")
STORE = issue("medium", "store.address", "No address printed.")
LOW = issue("low", "receipt.register", "Register unclear.")


@pytest.fixture(autouse=True)
async def _allowed(allow_user):
    await allow_user(USER)


async def parsed(harness, *issues: dict) -> int:
    raw = fixture("03")["raw"] | {"issues": list(issues)}
    harness.parser.default = output_of(raw)
    await harness.send_photo(user_id=USER)
    await harness.tasks.drain()
    return harness.last_keyboard()[0]


def last_text(harness) -> str:
    from aiogram.methods import EditMessageText

    for call in reversed(harness.session.calls):
        if isinstance(call, EditMessageText):
            return call.text
        if call in harness.sent_messages:
            return call.text
    raise AssertionError("nothing sent")


async def resolutions(session_factory) -> dict[str, str]:
    async with session_factory() as session:
        rows = await session.execute(text("select message, resolution from receipt_issues"))
        return {message: resolution for message, resolution in rows}


async def test_the_summary_offers_the_review_with_the_count(harness):
    await parsed(harness, TOTAL, LINE, STORE, LOW)

    assert harness.button_texts() == [ITEMS, "⚠️ Review (3)", PHOTO, DELETE]


async def test_low_issues_alone_give_no_review_button(harness):
    await parsed(harness, LOW)

    assert harness.button_texts() == [ITEMS, PHOTO, DELETE]


async def test_the_walk_opens_on_the_first_high_issue(harness):
    summary_id = await parsed(harness, LINE, TOTAL, LOW)

    await harness.tap(USER, "⚠️ Review (2)")

    body = last_text(harness)
    assert "Issue 1 of 2" in body
    assert "🔴" in body
    assert "The total looks too high." in body
    assert "Current value:</b> 7.58 €" in body
    assert harness.button_texts() == [CORRECT, ENTER, SKIP, CLOSE]
    assert harness.last_keyboard()[0] != summary_id


async def test_an_item_issue_names_the_item_and_a_non_editable_one_offers_no_entry(harness):
    await parsed(harness, LINE, STORE)

    await harness.tap(USER, "⚠️ Review (2)")
    body = last_text(harness)
    assert "🟡" in body
    assert "Cervesa Free Limo" in body
    assert "Current value:</b> 4.80 €" in body
    assert harness.button_texts() == [CORRECT, ENTER, SKIP, CLOSE]

    await harness.tap(USER, SKIP)
    body = last_text(harness)
    assert "Issue 2 of 2" in body
    assert "No address printed." in body
    assert "Current value" not in body
    assert "Item:" not in body
    assert harness.button_texts() == [CORRECT, SKIP, CLOSE]


async def test_correct_confirms_and_shows_the_next_issue(harness, session_factory):
    await parsed(harness, TOTAL, STORE)
    await harness.tap(USER, "⚠️ Review (2)")

    await harness.tap(USER, CORRECT)

    assert "Issue 2 of 2" in last_text(harness)
    assert await resolutions(session_factory) == {
        "The total looks too high.": "confirmed",
        "No address printed.": "open",
    }


async def test_skip_marks_skipped_and_the_count_on_the_card_stays(harness, session_factory):
    await parsed(harness, TOTAL, STORE)
    await harness.tap(USER, "⚠️ Review (2)")
    await harness.tap(USER, SKIP)
    await harness.tap(USER, CORRECT)

    assert await resolutions(session_factory) == {
        "The total looks too high.": "skipped",
        "No address printed.": "confirmed",
    }
    assert "2 reviewed: 0 corrected, 1 confirmed, 1 skipped" == last_text(harness)

    await harness.tap(USER, BACK)

    assert "Consum" in last_text(harness)
    assert harness.button_texts() == [ITEMS, "⚠️ Review (1)", PHOTO, DELETE, CLOSE]


async def test_back_after_resolving_everything_drops_the_review_button(harness):
    await parsed(harness, TOTAL)
    await harness.tap(USER, "⚠️ Review (1)")
    await harness.tap(USER, CORRECT)

    assert "1 reviewed: 0 corrected, 1 confirmed, 0 skipped" == last_text(harness)
    assert harness.button_texts() == [BACK]

    await harness.tap(USER, BACK)

    assert harness.button_texts() == [ITEMS, PHOTO, DELETE, CLOSE]


async def test_the_card_offers_the_review_and_starts_the_same_walk(harness):
    await parsed(harness, TOTAL, STORE)
    await harness.tap(USER, DELETE)
    await harness.tap(USER, BACK)
    assert harness.button_texts() == [ITEMS, "⚠️ Review (2)", PHOTO, DELETE, CLOSE]

    await harness.tap(USER, "⚠️ Review (2)")

    assert "Issue 1 of 2" in last_text(harness)
    assert "The total looks too high." in last_text(harness)


async def test_a_card_without_reviewable_issues_has_no_review_button(harness):
    await parsed(harness, LOW)
    await harness.tap(USER, DELETE)

    await harness.tap(USER, BACK)

    assert harness.button_texts() == [ITEMS, PHOTO, DELETE, CLOSE]


async def test_close_mid_walk_ends_the_dialog_and_keeps_the_issues_open(harness, session_factory):
    await parsed(harness, TOTAL, STORE)
    await harness.tap(USER, "⚠️ Review (2)")
    await harness.tap(USER, CORRECT)

    await harness.tap(USER, CLOSE)

    assert harness.last_keyboard()[1].inline_keyboard == []
    assert (await resolutions(session_factory))["No address printed."] == "open"


async def test_enter_value_opens_the_input_window_and_back_returns_to_the_issue(harness):
    await parsed(harness, TOTAL)
    await harness.tap(USER, "⚠️ Review (1)")

    await harness.tap(USER, ENTER)
    assert harness.button_texts() == [BACK]

    await harness.tap(USER, BACK)
    assert "Issue 1 of 1" in last_text(harness)
    assert harness.button_texts() == [CORRECT, ENTER, SKIP, CLOSE]


async def test_an_issue_resolved_elsewhere_is_skipped_silently(harness, session_factory):
    await parsed(harness, TOTAL, STORE, LINE)
    await harness.tap(USER, "⚠️ Review (3)")
    async with session_factory() as session:
        await session.execute(
            text(
                "update receipt_issues set resolution = 'confirmed', resolved_at = now() "
                "where message = 'No address printed.'"
            )
        )
        await session.commit()

    await harness.tap(USER, CORRECT)

    body = last_text(harness)
    assert "Line math is off." in body
    assert "Issue 3 of 3" in body


async def test_a_walk_with_nothing_left_goes_straight_to_the_card(harness, session_factory):
    await parsed(harness, TOTAL)
    data = harness.last_keyboard()[1].inline_keyboard[0][1].callback_data
    summary_id = harness.last_keyboard()[0]
    async with session_factory() as session:
        await session.execute(
            text("update receipt_issues set resolution = 'confirmed', resolved_at = now()")
        )
        await session.commit()

    await harness.press(USER, data, summary_id)

    assert "Consum" in last_text(harness)
    assert harness.button_texts() == [ITEMS, PHOTO, DELETE, CLOSE]


async def test_a_photo_sent_mid_walk_is_saved(harness, session_factory):
    await parsed(harness, TOTAL)
    await harness.tap(USER, "⚠️ Review (1)")

    await harness.send_photo(user_id=USER, file_id="second")
    await harness.tasks.drain()

    assert [m.text for m in harness.sent_messages].count(i18n.get("receipt-saved")) == 2
    async with session_factory() as session:
        count = (await session.execute(text("select count(*) from receipts"))).scalar_one()
    assert count == 2


async def test_a_review_tap_on_a_deleted_receipt_alerts_and_removes_the_keyboard(harness):
    summary_id = await parsed(harness, TOTAL)
    data = harness.last_keyboard()[1].inline_keyboard[0][1].callback_data
    await harness.tap(USER, DELETE)
    await harness.tap(USER, "🗑 Yes, delete")

    await harness.press(USER, data, summary_id)

    alert = harness.session.calls[-2]
    assert isinstance(alert, AnswerCallbackQuery)
    assert (alert.text, alert.show_alert) == (i18n.get("card-deleted-alert"), True)
    removal = harness.session.calls[-1]
    assert isinstance(removal, EditMessageReplyMarkup)
    assert removal.reply_markup is None


async def test_the_message_of_an_issue_is_escaped(harness):
    await parsed(harness, issue("high", "store.address", "Read <b>this</b> & that"))

    await harness.tap(USER, "⚠️ Review (1)")

    assert "Read &lt;b&gt;this&lt;/b&gt; &amp; that" in last_text(harness)


async def test_a_receipt_deleted_mid_walk_alerts_and_ends_the_dialog(harness, session_factory):
    await parsed(harness, TOTAL, STORE)
    await harness.tap(USER, "⚠️ Review (2)")
    async with session_factory() as session:
        await session.execute(text("update receipts set deleted_at = now()"))
        await session.commit()

    await harness.tap(USER, CORRECT)

    alerts = [c for c in harness.session.calls if isinstance(c, AnswerCallbackQuery) and c.text]
    assert (alerts[-1].text, alerts[-1].show_alert) == (i18n.get("card-deleted-alert"), True)
    assert harness.last_keyboard()[1].inline_keyboard == []
