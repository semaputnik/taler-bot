"""Tags on the receipt card: the line, the `#️⃣ Tags` button and its window."""

import pytest
from aiogram.methods import AnswerCallbackQuery
from sqlalchemy import text

from src.bot.i18n import DEFAULT_LOCALE, create_translator_hub
from src.integration.llm import LLMError
from tests.stubs import fixture, output_of

USER = 7
CATEGORY = "🏷 Category"
TAGS = "#️⃣ Tags"
CLEAR = "🧹 Clear"
BACK = "◀ Back"
REPARSE = "🔄 Re-parse"
CONFIRM = "🔄 Yes, read again"

i18n = create_translator_hub().get_translator_by_locale(DEFAULT_LOCALE)


@pytest.fixture(autouse=True)
async def _allowed(allow_user):
    await allow_user(USER)


async def parsed(harness, **kwargs) -> int:
    await harness.send_photo(user_id=USER, **kwargs)
    await harness.tasks.drain()
    return harness.last_keyboard()[0]


async def stored_tags(session_factory) -> list[str]:
    async with session_factory() as session:
        rows = await session.execute(
            text(
                "select coalesce(array_agg(t.name order by t.name) filter (where t.id is not null),"
                " '{}') from expenses e left join expense_tags et on et.expense_id = e.id"
                " left join tags t on t.id = et.tag_id group by e.id order by e.id"
            )
        )
        return [row[0] for row in rows][-1]


def tag_lines(harness) -> list[str]:
    return [line for line in harness.last_text().splitlines() if line.startswith("Tags:")]


async def test_the_button_sits_in_the_row_of_the_category_button(harness):
    await parsed(harness)

    rows = [[b.text for b in row] for row in harness.last_keyboard()[1].inline_keyboard]
    assert rows == [
        ["📋 Items", "⚠️ Review (3)"],
        [CATEGORY, TAGS],
        ["🖼 Photo", "🗑 Delete"],
        [REPARSE],
        ["✖ Close"],
    ]


async def test_an_untagged_card_has_no_tags_line(harness):
    await parsed(harness)

    assert tag_lines(harness) == []


async def test_a_line_sets_the_tags_edits_the_card_in_place_and_saves(harness, session_factory):
    card_id = await parsed(harness)
    await harness.tap(USER, TAGS)
    assert harness.button_texts() == [CLEAR, BACK]
    assert harness.last_text() == i18n.get("expense-edit-tags", tags=i18n.get("item-not-specified"))

    await harness.send_text("Kids, holiday", user_id=USER)

    assert harness.last_keyboard()[0] == card_id
    lines = harness.last_text().splitlines()
    assert lines[lines.index("Category: Groceries") + 1] == "Tags: #holiday #kids"
    assert CATEGORY in harness.button_texts()
    assert await stored_tags(session_factory) == ["holiday", "kids"]


async def test_the_window_shows_the_current_tags_and_a_new_line_replaces_them(
    harness, session_factory
):
    await parsed(harness)
    await harness.tap(USER, TAGS)
    await harness.send_text("kids", user_id=USER)
    await harness.tap(USER, TAGS)
    assert "#kids" in harness.last_text()

    await harness.send_text("trip", user_id=USER)

    assert tag_lines(harness) == ["Tags: #trip"]
    assert await stored_tags(session_factory) == ["trip"]


async def test_clear_empties_the_tags_and_drops_the_line(harness, session_factory):
    await parsed(harness)
    await harness.tap(USER, TAGS)
    await harness.send_text("kids", user_id=USER)
    await harness.tap(USER, TAGS)

    await harness.tap(USER, CLEAR)

    assert tag_lines(harness) == []
    assert TAGS in harness.button_texts()
    assert await stored_tags(session_factory) == []


@pytest.mark.parametrize("typed", [",".join(f"t{i}" for i in range(11)), "x" * 33])
async def test_a_bad_line_is_refused_and_changes_nothing(harness, session_factory, typed):
    await parsed(harness)
    await harness.tap(USER, TAGS)

    await harness.send_text(typed, user_id=USER)

    assert i18n.get("expense-edit-tags-error") in harness.last_text()
    assert harness.button_texts() == [CLEAR, BACK]
    assert await stored_tags(session_factory) == []


async def test_a_number_typed_in_the_window_is_a_tag_not_a_new_entry(harness, session_factory):
    await parsed(harness)
    await harness.tap(USER, TAGS)

    await harness.send_text("2026", user_id=USER)

    assert tag_lines(harness) == ["Tags: #2026"]
    assert await stored_tags(session_factory) == ["2026"]


async def test_back_returns_to_the_card(harness):
    await parsed(harness)
    await harness.tap(USER, TAGS)

    await harness.tap(USER, BACK)

    assert TAGS in harness.button_texts()
    assert "Category:" in harness.last_text()


@pytest.mark.parametrize("outcome", ["failed", "not_receipt", "duplicate"])
async def test_a_card_without_an_expense_has_no_tags_button(harness, outcome):
    if outcome == "failed":
        harness.parser.error = LLMError("timed out")
    elif outcome == "not_receipt":
        raw = fixture("03")["raw"] | {"is_receipt": False, "items": [], "issues": []}
        harness.parser.default = output_of(raw)
    else:
        await parsed(harness, file_id="a")

    await parsed(harness, file_id="b")

    assert TAGS not in harness.button_texts()
    assert tag_lines(harness) == []


async def test_a_stale_tags_button_of_a_deleted_receipt_alerts(harness, session_factory):
    card_id = await parsed(harness)
    callback = next(
        b.callback_data
        for row in harness.last_keyboard()[1].inline_keyboard
        for b in row
        if b.text == TAGS
    )
    async with session_factory() as session:
        await session.execute(text("update receipts set deleted_at = now()"))
        await session.execute(text("update expenses set deleted_at = now()"))
        await session.commit()

    await harness.press(USER, callback, card_id)

    alerts = [c for c in harness.session.calls if isinstance(c, AnswerCallbackQuery) and c.text]
    assert (alerts[-1].text, alerts[-1].show_alert) == (i18n.get("card-deleted-alert"), True)


async def test_a_line_typed_after_the_receipt_was_deleted_shows_the_deleted_card(
    harness, session_factory
):
    await parsed(harness)
    await harness.tap(USER, TAGS)
    async with session_factory() as session:
        await session.execute(text("update receipts set deleted_at = now()"))
        await session.execute(text("update expenses set deleted_at = now()"))
        await session.commit()

    await harness.send_text("kids", user_id=USER)

    assert harness.last_text() == i18n.get("card-deleted")
    assert await stored_tags(session_factory) == []


async def test_a_reparse_keeps_the_tags(harness, session_factory):
    await parsed(harness)
    await harness.tap(USER, TAGS)
    await harness.send_text("kids", user_id=USER)
    harness.parser.default = output_of(fixture("04")["raw"])

    await harness.tap(USER, REPARSE)
    await harness.tap(USER, CONFIRM)
    await harness.tasks.drain()

    assert "Ametller" in harness.last_text()
    assert tag_lines(harness) == ["Tags: #kids"]
    assert await stored_tags(session_factory) == ["kids"]
