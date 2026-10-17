"""The issue review walk (ReceiptCard `issue` and `review_done` windows), end to end."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from aiogram.methods import AnswerCallbackQuery, EditMessageReplyMarkup
from aiogram.types import Voice
from sqlalchemy import text

from src.bot.i18n import DEFAULT_LOCALE, create_translator_hub
from tests.stubs import fixture, output_of

USER = 7
ITEMS = "📋 Items"
PHOTO = "🖼 Photo"
DELETE = "🗑 Delete"
CLOSE = "✖ Close"
REPARSE = "🔄 Re-parse"
CORRECT = "✅ Correct"
ENTER = "✏️ Enter value"
SKIP = "⏭ Skip"
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
DATE = issue("high", "receipt.purchased_at", "The date looks wrong.")
CARD = issue("high", "payment.card_last4", "Unseen card ending.")


@pytest.fixture(autouse=True)
async def _allowed(allow_user):
    await allow_user(USER)


async def parsed(harness, *issues: dict) -> int:
    raw = fixture("03")["raw"] | {"issues": list(issues)}
    harness.parser.default = output_of(raw)
    await harness.send_photo(user_id=USER)
    await harness.tasks.drain()
    return harness.last_keyboard()[0]


async def resolutions(session_factory) -> dict[str, str]:
    async with session_factory() as session:
        rows = await session.execute(text("select message, resolution from receipt_issues"))
        return {message: resolution for message, resolution in rows}


async def test_the_summary_offers_the_review_with_the_count(harness):
    await parsed(harness, TOTAL, LINE, STORE, LOW)

    assert harness.button_texts() == [ITEMS, "⚠️ Review (3)", PHOTO, DELETE, REPARSE, CLOSE]


async def test_low_issues_alone_give_no_review_button(harness):
    await parsed(harness, LOW)

    assert harness.button_texts() == [ITEMS, PHOTO, DELETE, REPARSE, CLOSE]


async def test_the_walk_opens_on_the_first_high_issue(harness):
    summary_id = await parsed(harness, LINE, TOTAL, LOW)

    await harness.tap(USER, "⚠️ Review (2)")

    body = harness.last_text()
    assert "Issue 1 of 2" in body
    assert "🔴" in body
    assert "The total looks too high." in body
    assert "Current value:</b> 7.58 €" in body
    assert harness.button_texts() == [CORRECT, ENTER, SKIP, BACK]
    assert harness.last_keyboard()[0] == summary_id  # the card is edited in place
    assert len(harness.sent_messages) == 2  # "Saved" and the card


async def test_an_item_issue_names_the_item_and_a_non_editable_one_offers_no_entry(harness):
    await parsed(harness, LINE, STORE)

    await harness.tap(USER, "⚠️ Review (2)")
    body = harness.last_text()
    assert "🟡" in body
    assert "Cervesa Free Limo" in body
    assert "Current value:</b> 4.80 €" in body
    assert harness.button_texts() == [CORRECT, ENTER, SKIP, BACK]

    await harness.tap(USER, SKIP)
    body = harness.last_text()
    assert "Issue 2 of 2" in body
    assert "No address printed." in body
    assert "Current value" not in body
    assert "Item:" not in body
    assert harness.button_texts() == [CORRECT, SKIP, BACK]


async def test_correct_confirms_and_shows_the_next_issue(harness, session_factory):
    await parsed(harness, TOTAL, STORE)
    await harness.tap(USER, "⚠️ Review (2)")

    await harness.tap(USER, CORRECT)

    assert "Issue 2 of 2" in harness.last_text()
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
    assert "2 reviewed: 0 corrected, 1 confirmed, 1 skipped" == harness.last_text()

    await harness.tap(USER, BACK)

    assert "Consum" in harness.last_text()
    assert harness.button_texts() == [ITEMS, "⚠️ Review (1)", PHOTO, DELETE, REPARSE, CLOSE]


async def test_back_after_resolving_everything_drops_the_review_button(harness):
    await parsed(harness, TOTAL)
    await harness.tap(USER, "⚠️ Review (1)")
    await harness.tap(USER, CORRECT)

    assert "1 reviewed: 0 corrected, 1 confirmed, 0 skipped" == harness.last_text()
    assert harness.button_texts() == [BACK]

    await harness.tap(USER, BACK)

    assert harness.button_texts() == [ITEMS, PHOTO, DELETE, REPARSE, CLOSE]


async def test_the_card_offers_the_review_and_starts_the_same_walk(harness):
    await parsed(harness, TOTAL, STORE)
    assert harness.button_texts() == [ITEMS, "⚠️ Review (2)", PHOTO, DELETE, REPARSE, CLOSE]

    await harness.tap(USER, "⚠️ Review (2)")

    assert "Issue 1 of 2" in harness.last_text()
    assert "The total looks too high." in harness.last_text()


async def test_a_card_without_reviewable_issues_has_no_review_button(harness):
    await parsed(harness, LOW)

    assert harness.button_texts() == [ITEMS, PHOTO, DELETE, REPARSE, CLOSE]


async def test_back_mid_walk_lands_on_the_card_and_keeps_the_issues_open(harness, session_factory):
    await parsed(harness, TOTAL, STORE)
    await harness.tap(USER, "⚠️ Review (2)")
    await harness.tap(USER, CORRECT)

    await harness.tap(USER, BACK)

    assert "Consum" in harness.last_text()
    assert harness.button_texts() == [ITEMS, "⚠️ Review (1)", PHOTO, DELETE, REPARSE, CLOSE]
    assert (await resolutions(session_factory))["No address printed."] == "open"


async def test_enter_value_opens_the_input_window_and_back_returns_to_the_issue(harness):
    await parsed(harness, TOTAL)
    await harness.tap(USER, "⚠️ Review (1)")

    await harness.tap(USER, ENTER)
    assert "Enter the total (a number with a point, like 12.50)" in harness.last_text()
    assert harness.button_texts() == [BACK]

    await harness.tap(USER, BACK)
    assert "Issue 1 of 1" in harness.last_text()
    assert harness.button_texts() == [CORRECT, ENTER, SKIP, BACK]


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

    body = harness.last_text()
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

    assert "Consum" in harness.last_text()
    assert harness.button_texts() == [ITEMS, PHOTO, DELETE, REPARSE, CLOSE]


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

    assert "Read &lt;b&gt;this&lt;/b&gt; &amp; that" in harness.last_text()


async def test_a_receipt_deleted_mid_walk_alerts_and_ends_the_dialog(harness, session_factory):
    await parsed(harness, TOTAL, STORE)
    await harness.tap(USER, "⚠️ Review (2)")
    async with session_factory() as session:
        await session.execute(text("update receipts set deleted_at = now()"))
        await session.commit()

    await harness.tap(USER, CORRECT)

    alerts = [c for c in harness.session.calls if isinstance(c, AnswerCallbackQuery) and c.text]
    assert (alerts[-1].text, alerts[-1].show_alert) == (i18n.get("card-deleted-alert"), True)
    assert harness.last_text() == i18n.get("card-deleted")
    assert harness.last_keyboard()[1].inline_keyboard == []


async def header(session_factory) -> tuple:
    async with session_factory() as session:
        row = await session.execute(text("select total, purchased_at, card_last4 from receipts"))
        return row.one()


async def edits(session_factory) -> list[tuple]:
    async with session_factory() as session:
        rows = await session.execute(
            text(
                "select e.field, e.value::text, e.item_ref is not null, i.message "
                "from receipt_edits e join receipt_issues i on i.id = e.issue_id"
            )
        )
        return [tuple(r) for r in rows]


async def test_the_prompt_names_the_field_and_the_format(harness):
    await parsed(harness, DATE, CARD, TOTAL)

    await harness.tap(USER, "⚠️ Review (3)")
    await harness.tap(USER, ENTER)
    assert "Enter the date and time (dd.mm.yyyy hh:mm)" in harness.last_text()
    await harness.tap(USER, BACK)
    await harness.tap(USER, SKIP)
    await harness.tap(USER, ENTER)
    assert "Enter the card ending (four digits)" in harness.last_text()
    await harness.tap(USER, BACK)
    await harness.tap(USER, SKIP)
    await harness.tap(USER, ENTER)
    assert "Enter the total (a number with a point, like 12.50)" in harness.last_text()


@pytest.mark.parametrize(
    ("issue_", "bad"),
    [(DATE, "yesterday"), (TOTAL, "abc"), (CARD, "123")],
)
async def test_a_bad_value_shows_the_error_and_keeps_the_issue_open(
    harness, session_factory, issue_, bad
):
    await parsed(harness, issue_)
    await harness.tap(USER, "⚠️ Review (1)")
    await harness.tap(USER, ENTER)
    before = await header(session_factory)

    await harness.send_text(bad, user_id=USER)

    body = harness.last_text()
    assert "Enter the" in body
    assert "❌ Not accepted" in body
    assert harness.button_texts() == [BACK]
    assert await header(session_factory) == before
    assert set((await resolutions(session_factory)).values()) == {"open"}


async def test_a_non_text_message_gets_the_hint(harness):
    await parsed(harness, TOTAL)
    await harness.tap(USER, "⚠️ Review (1)")
    await harness.tap(USER, ENTER)

    await harness._feed(USER, voice=Voice(file_id="v", file_unique_id="v", duration=1))

    assert "❌ Not accepted" in harness.last_text()
    assert harness.button_texts() == [BACK]


async def test_back_from_the_entry_clears_the_error(harness):
    await parsed(harness, TOTAL)
    await harness.tap(USER, "⚠️ Review (1)")
    await harness.tap(USER, ENTER)
    await harness.send_text("abc", user_id=USER)

    await harness.tap(USER, BACK)
    await harness.tap(USER, ENTER)

    assert "Not accepted" not in harness.last_text()


async def test_a_good_total_corrects_the_receipt_and_advances(harness, session_factory):
    await parsed(harness, TOTAL, STORE)
    await harness.tap(USER, "⚠️ Review (2)")
    await harness.tap(USER, ENTER)

    await harness.send_text("12,50", user_id=USER)

    assert "Issue 2 of 2" in harness.last_text()
    assert (await header(session_factory))[0] == Decimal("12.50")
    assert (await resolutions(session_factory))["The total looks too high."] == "corrected"
    assert await edits(session_factory) == [
        ("total", '"12.50"', False, "The total looks too high.")
    ]

    await harness.tap(USER, SKIP)
    assert "2 reviewed: 1 corrected, 0 confirmed, 1 skipped" == harness.last_text()
    await harness.tap(USER, BACK)
    assert "Total: <b>12.50 €</b>" in harness.last_text()


async def test_a_good_date_is_stored_in_utc_and_shown_in_the_users_zone(harness, session_factory):
    await parsed(harness, DATE)
    await harness.tap(USER, "⚠️ Review (1)")
    await harness.tap(USER, ENTER)

    await harness.send_text("05.07.2026 18:30", user_id=USER)

    stored = (await header(session_factory))[1]
    assert stored.astimezone(UTC) == datetime(2026, 7, 5, 16, 30, tzinfo=UTC)
    await harness.tap(USER, BACK)
    assert "05.07.2026 18:30" in harness.last_text()


async def test_a_good_card_ending_is_stored(harness, session_factory):
    await parsed(harness, CARD)
    await harness.tap(USER, "⚠️ Review (1)")
    await harness.tap(USER, ENTER)

    await harness.send_text("4321", user_id=USER)

    assert (await header(session_factory))[2] == "4321"
    await harness.tap(USER, BACK)
    assert "•4321" in harness.last_text()


async def test_an_item_correction_changes_that_item(harness, session_factory):
    await parsed(harness, LINE)
    await harness.tap(USER, "⚠️ Review (1)")
    await harness.tap(USER, ENTER)

    await harness.send_text("5.10", user_id=USER)

    assert "1 corrected" in harness.last_text()
    assert await edits(session_factory) == [("line_total", '"5.10"', True, "Line math is off.")]
    await harness.tap(USER, BACK)
    await harness.tap(USER, ITEMS)
    await harness.tap(USER, next(t for t in harness.button_texts() if "Cervesa Free Limo" in t))
    assert "<b>Line total:</b> 5.10 €" in harness.last_text()


async def test_a_value_for_a_receipt_deleted_meanwhile_alerts_and_ends_the_dialog(
    harness, session_factory
):
    await parsed(harness, TOTAL)
    await harness.tap(USER, "⚠️ Review (1)")
    await harness.tap(USER, ENTER)
    async with session_factory() as session:
        await session.execute(text("update receipts set deleted_at = now()"))
        await session.commit()

    await harness.send_text("12.50", user_id=USER)

    assert i18n.get("card-deleted-alert") in [m.text for m in harness.sent_messages]
    assert harness.last_text() == i18n.get("card-deleted")
    assert harness.last_keyboard()[1].inline_keyboard == []
