"""Rename from the issue review (ReceiptCard `issue` and `issue_rename` windows)."""

import pytest
from sqlalchemy import text

from src.bot.i18n import DEFAULT_LOCALE, create_translator_hub
from tests.bot.test_issue_review import CORRECT, ENTER, SKIP, TOTAL, issue, parsed, resolutions
from tests.stubs import fixture, output_of

USER = 7
BACK = "◀ Back"
RENAME = "✏️ Rename"
REVIEW = "⚠️ Review (1)"
FREE_LIMO = "Cervesa Free Limo · 6 pcs · 4.80 €"
NAME_ISSUE = issue("medium", "items.name_normalized", "Name is unclear.", "CERV FREE LIMO.")
ORPHAN_ISSUE = issue("medium", "items.name_normalized", "Name is unclear.", "NOT ON RECEIPT")

i18n = create_translator_hub().get_translator_by_locale(DEFAULT_LOCALE)
ERROR = i18n.get("issue-input-error", hint="{hint}").split("{hint}")[0]


@pytest.fixture(autouse=True)
async def _allowed(allow_user):
    await allow_user(USER)


async def test_a_name_issue_offers_rename_and_not_enter_value(harness):
    await parsed(harness, NAME_ISSUE)

    await harness.tap(USER, REVIEW)

    assert "Cervesa Free Limo" in harness.last_text()
    assert harness.button_texts() == [CORRECT, RENAME, SKIP, BACK]
    assert ENTER not in harness.button_texts()


async def test_a_name_issue_without_a_matched_item_offers_no_rename(harness):
    await parsed(harness, ORPHAN_ISSUE)

    await harness.tap(USER, REVIEW)

    assert RENAME not in harness.button_texts()
    assert ENTER not in harness.button_texts()


async def test_rename_opens_the_input_and_back_returns_to_the_unresolved_issue(
    harness, session_factory
):
    await parsed(harness, NAME_ISSUE)
    await harness.tap(USER, REVIEW)

    await harness.tap(USER, RENAME)
    prompt = harness.last_text()
    assert "Enter the name (free text)" in prompt
    assert "Current value:</b> Cervesa Free Limo" in prompt
    assert harness.button_texts() == [BACK]

    await harness.tap(USER, BACK)
    assert "Issue 1 of 1" in harness.last_text()
    assert harness.button_texts() == [CORRECT, RENAME, SKIP, BACK]
    assert await resolutions(session_factory) == {"Name is unclear.": "open"}


async def test_a_new_name_renames_the_product_resolves_the_issue_and_counts_it(
    harness, session_factory
):
    await parsed(harness, NAME_ISSUE)
    await harness.tap(USER, REVIEW)
    await harness.tap(USER, RENAME)

    await harness.send_text("Cerveza <Free> Limón", user_id=USER)

    assert "1 corrected" in harness.last_text()
    assert (await resolutions(session_factory))["Name is unclear."] == "corrected"
    await harness.tap(USER, BACK)
    await harness.tap(USER, "📋 Items")
    assert "Cerveza <Free> Limón · 6 pcs · 4.80 €" in harness.button_texts()
    await harness.tap(USER, "Cerveza <Free> Limón · 6 pcs · 4.80 €")
    assert harness.last_text().startswith("<b>Cerveza &lt;Free&gt; Limón</b>")


async def test_the_new_name_shows_on_another_receipt_of_the_store(harness):
    await parsed(harness, NAME_ISSUE)
    await harness.tap(USER, REVIEW)
    await harness.tap(USER, RENAME)
    await harness.send_text("Cerveza Limón", user_id=USER)

    raw = fixture("03")["raw"]
    harness.parser.default = output_of(
        raw | {"issues": [], "receipt": raw["receipt"] | {"number": "N2"}}
    )
    await harness.send_photo(user_id=USER, file_id="f2")
    await harness.tasks.drain()
    await harness.tap(USER, "📋 Items")
    await harness.tap(USER, "Cerveza Limón · 6 pcs · 4.80 €")
    assert harness.last_text().startswith("<b>Cerveza Limón</b>")


async def test_rename_moves_on_to_the_next_issue(harness):
    await parsed(harness, NAME_ISSUE, TOTAL)
    await harness.tap(USER, "⚠️ Review (2)")
    assert "The total looks too high." in harness.last_text()
    await harness.tap(USER, SKIP)
    assert "Name is unclear." in harness.last_text()
    await harness.tap(USER, RENAME)

    await harness.send_text("New name", user_id=USER)

    assert "1 corrected" in harness.last_text()


async def test_an_empty_name_shows_the_error_and_keeps_the_issue_open(harness, session_factory):
    await parsed(harness, NAME_ISSUE)
    await harness.tap(USER, REVIEW)
    await harness.tap(USER, RENAME)

    await harness.send_text("   ", user_id=USER)

    assert ERROR in harness.last_text()
    assert harness.button_texts() == [BACK]
    assert await resolutions(session_factory) == {"Name is unclear.": "open"}
    await harness.tap(USER, BACK)
    assert harness.button_texts() == [CORRECT, RENAME, SKIP, BACK]


async def test_a_name_for_a_receipt_deleted_meanwhile_alerts_and_ends_the_dialog(
    harness, session_factory
):
    await parsed(harness, NAME_ISSUE)
    await harness.tap(USER, REVIEW)
    await harness.tap(USER, RENAME)
    async with session_factory() as session:
        await session.execute(text("update receipts set deleted_at = now()"))
        await session.commit()

    await harness.send_text("New name", user_id=USER)

    assert i18n.get("card-deleted-alert") in [m.text for m in harness.sent_messages]
    assert harness.last_text() == i18n.get("card-deleted")
    assert harness.last_keyboard()[1].inline_keyboard == []


async def test_an_issue_resolved_elsewhere_while_typing_is_skipped(harness, session_factory):
    await parsed(harness, NAME_ISSUE)
    await harness.tap(USER, REVIEW)
    await harness.tap(USER, RENAME)
    async with session_factory() as session:
        await session.execute(text("update receipt_issues set resolution = 'confirmed'"))
        await session.commit()

    await harness.send_text("New name", user_id=USER)

    assert "0 corrected" in harness.last_text()
    assert await resolutions(session_factory) == {"Name is unclear.": "confirmed"}
