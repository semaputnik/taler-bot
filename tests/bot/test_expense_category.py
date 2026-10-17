"""The expense category on the receipt card: the line, the `🏷 Category` window and its pick."""

import pytest
from aiogram.methods import AnswerCallbackQuery
from sqlalchemy import text

from src.bot.handlers.dialog.receipt_card.common import EXPENSE_CATEGORIES
from src.bot.i18n import DEFAULT_LOCALE, create_translator_hub
from src.domain.enums import ExpenseCategory
from src.integration.llm import LLMError
from tests.stubs import fixture, output_of

USER = 7
CATEGORY = "🏷 Category"
BACK = "◀ Back"
DELETE = "🗑 Delete"

i18n = create_translator_hub().get_translator_by_locale(DEFAULT_LOCALE)


@pytest.fixture(autouse=True)
async def _allowed(allow_user):
    await allow_user(USER)


async def parsed(harness, **kwargs) -> int:
    await harness.send_photo(user_id=USER, **kwargs)
    await harness.tasks.drain()
    return harness.last_keyboard()[0]


async def stored_category(session_factory) -> list[str]:
    async with session_factory() as session:
        rows = await session.execute(text("select category from expenses order by id"))
        return [row[0] for row in rows]


async def test_a_parsed_card_shows_the_category_after_the_payment_and_the_button(harness):
    await parsed(harness)

    lines = harness.last_text().splitlines()
    payment = next(i for i, line in enumerate(lines) if line.startswith("Payment:"))
    assert lines[payment + 1] == "Category: Groceries"
    assert CATEGORY in harness.button_texts()


async def test_the_window_lists_the_twelve_categories_two_per_row_and_marks_the_current(harness):
    await parsed(harness)

    await harness.tap(USER, CATEGORY)

    texts = harness.button_texts()
    assert len(texts) == 13
    assert "✓ Groceries" in texts
    assert texts[-1] == BACK
    rows = [len(row) for row in harness.last_keyboard()[1].inline_keyboard]
    assert rows == [2] * 6 + [1]
    assert harness.last_text() == i18n.get("expense-category-prompt")


async def test_a_pick_changes_the_line_the_mark_and_the_database(harness, session_factory):
    card_id = await parsed(harness)
    await harness.tap(USER, CATEGORY)

    await harness.tap(USER, "Health")

    assert harness.last_keyboard()[0] == card_id
    assert "Category: Health" in harness.last_text()
    assert "Category: Groceries" not in harness.last_text()
    assert await stored_category(session_factory) == ["health"]
    await harness.tap(USER, CATEGORY)
    assert "✓ Health" in harness.button_texts()
    assert "✓ Groceries" not in harness.button_texts()
    assert "Groceries" in harness.button_texts()


async def test_back_returns_to_the_card_without_a_change(harness, session_factory):
    await parsed(harness)
    await harness.tap(USER, CATEGORY)

    await harness.tap(USER, BACK)

    assert "Category: Groceries" in harness.last_text()
    assert CATEGORY in harness.button_texts()
    assert await stored_category(session_factory) == ["groceries"]


@pytest.mark.parametrize("outcome", ["failed", "not_receipt", "duplicate"])
async def test_a_card_without_an_expense_shows_neither_the_line_nor_the_button(harness, outcome):
    if outcome == "failed":
        harness.parser.error = LLMError("timed out")
    elif outcome == "not_receipt":
        raw = fixture("03")["raw"] | {"is_receipt": False, "items": [], "issues": []}
        harness.parser.default = output_of(raw)
    else:
        await parsed(harness, file_id="a")

    await parsed(harness, file_id="b")

    assert "Category:" not in harness.last_text()
    assert CATEGORY not in harness.button_texts()


async def test_a_pick_on_a_deleted_receipt_alerts_and_changes_nothing(harness, session_factory):
    await parsed(harness)
    await harness.tap(USER, CATEGORY)
    async with session_factory() as session:
        await session.execute(text("update receipts set deleted_at = now()"))
        await session.execute(text("update expenses set deleted_at = now()"))
        await session.commit()

    await harness.tap(USER, "Rent")

    alerts = [c for c in harness.session.calls if isinstance(c, AnswerCallbackQuery) and c.text]
    assert (alerts[-1].text, alerts[-1].show_alert) == (i18n.get("card-deleted-alert"), True)
    assert harness.last_text() == i18n.get("card-deleted")
    assert await stored_category(session_factory) == ["groceries"]


async def test_the_category_button_of_an_older_card_opens_a_fresh_window(harness):
    first = await parsed(harness, file_id="a")
    await parsed(harness, file_id="b")
    sent = len(harness.sent_messages)

    await harness.press(USER, _category_callback(harness, first), first)

    assert len(harness.sent_messages) == sent + 1
    assert "✓ Groceries" in harness.button_texts()


def _category_callback(harness, message_id: int) -> str:
    for mid, markup in harness.keyboards():
        if mid == message_id:
            for row in markup.inline_keyboard:
                for button in row:
                    if button.text == CATEGORY:
                        return button.callback_data
    raise AssertionError("no category button")


def test_the_bots_expense_category_list_is_the_domains():
    assert set(EXPENSE_CATEGORIES) == {str(c) for c in ExpenseCategory}
    assert len(EXPENSE_CATEGORIES) == len(set(EXPENSE_CATEGORIES))


def test_every_expense_category_has_a_name():
    for category in ExpenseCategory:
        key = f"expense-category-{category.replace('_', '-')}"
        assert i18n.get(key) != key, key
