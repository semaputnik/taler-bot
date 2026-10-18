"""The ExpenseCard dialog: the card of an expense typed by hand, its edits, delete and close."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from aiogram.methods import AnswerCallbackQuery, EditMessageReplyMarkup, EditMessageText
from aiogram.types import InlineKeyboardMarkup
from sqlalchemy import text

from src.bot.i18n import DEFAULT_LOCALE, create_translator_hub
from src.services.expense import ExpenseService
from tests.helpers import add_manual_expense

USER = 7
AMOUNT = "✏️ Amount"
PAYEE = "🏪 Payee"
SOURCE = "💳 Source"
CATEGORY = "🏷 Category"
DATE = "📅 Date"
TAGS = "#️⃣ Tags"
DELETE = "🗑 Delete"
CLOSE = "✖ Close"
BACK = "◀ Back"
TYPE_NAME = "✏️ Type a name"
NEW_CARD = "➕ New card"
RENAME = "✏️ Rename"
CLEAR = "🧹 Clear"
OTHER_DATE = "✏️ Other date"
PHOTO_PROMPT = "Send me a photo of a receipt."
CARD_BUTTONS = [AMOUNT, PAYEE, SOURCE, CATEGORY, DATE, TAGS, DELETE, CLOSE]

i18n = create_translator_hub().get_translator_by_locale(DEFAULT_LOCALE)


def today() -> date:
    return datetime.now(ZoneInfo("Europe/Madrid")).date()


def shown(day: date) -> str:
    return day.strftime("%d.%m.%Y")


@pytest.fixture(autouse=True)
async def _allowed(allow_user):
    await allow_user(USER)


async def one(session_factory, sql: str):
    async with session_factory() as session:
        return tuple((await session.execute(text(sql))).one())


async def stored(session_factory) -> tuple:
    """amount, payee, source, category, spent_at, tags, deleted for the only expense."""
    return await one(
        session_factory,
        "select e.amount, p.name, s.name, e.category, e.spent_at,"
        " coalesce((select array_agg(t.name order by t.name) from expense_tags et"
        " join tags t on t.id = et.tag_id where et.expense_id = e.id), '{}'),"
        " e.deleted_at is not null"
        " from expenses e left join payees p on p.id = e.payee_id"
        " left join payment_sources s on s.id = e.payment_source_id"
        " order by e.id desc limit 1",
    )


async def entered(harness, amount: str = "12.50", payee: str = "Mercadona") -> int:
    """Run the whole entry (cash, Groceries, today, no tags); return the card's message id."""
    await harness.send_text(amount, user_id=USER)
    await harness.tap(USER, TYPE_NAME)
    await harness.send_text(payee, user_id=USER)
    await harness.tap(USER, "Cash")
    await harness.tap(USER, "Groceries")
    await harness.tap(USER, "Today")
    await harness.tap(USER, "⏭ Skip")
    return harness.last_keyboard()[0]


def card_lines(harness) -> list[str]:
    return harness.last_text().splitlines()


# --- the card ---------------------------------------------------------------------------------


async def test_the_entry_ends_on_the_expense_card(harness):
    await entered(harness)

    assert card_lines(harness) == [
        "💸 <b>Mercadona</b>",
        "",
        shown(today()),
        "Amount: <b>12.50 €</b>",
        "Paid with: Cash",
        "Category: Groceries",
        "",
        "#mercadona",
    ]
    assert harness.button_texts() == CARD_BUTTONS
    assert [len(r) for r in harness.last_keyboard()[1].inline_keyboard] == [2, 2, 2, 1, 1]


async def test_the_entry_message_loses_its_buttons_when_the_card_arrives(harness):
    await harness.send_text("12.50", user_id=USER)
    entry_id = harness.last_keyboard()[0]

    await harness.tap(USER, TYPE_NAME)
    await harness.send_text("Mercadona", user_id=USER)
    await harness.tap(USER, "Cash")
    await harness.tap(USER, "Groceries")
    await harness.tap(USER, "Today")
    await harness.tap(USER, "⏭ Skip")

    assert harness.last_keyboard()[0] != entry_id
    assert [m for mid, m in harness.keyboards() if mid == entry_id][-1] == InlineKeyboardMarkup(
        inline_keyboard=[]
    )


# --- amount -----------------------------------------------------------------------------------


async def test_a_number_typed_in_the_amount_window_is_the_new_amount(harness, session_factory):
    card_id = await entered(harness)
    messages = len(harness.sent_messages)

    await harness.tap(USER, AMOUNT)
    assert harness.last_text() == i18n.get("expense-edit-amount", amount="12.50 €")
    assert harness.button_texts() == [BACK]
    await harness.send_text("20,5", user_id=USER)

    assert len(harness.sent_messages) == messages  # edited in place, no new entry
    assert "Amount: <b>20.50 €</b>" in card_lines(harness)
    assert harness.last_keyboard()[0] == card_id
    assert (await stored(session_factory))[0] == pytest.approx(20.5)
    assert harness.button_texts() == CARD_BUTTONS


@pytest.mark.parametrize("typed", ["0", "0.00", "-5", "abc"])
async def test_a_refused_amount_keeps_the_window_and_the_value(harness, session_factory, typed):
    await entered(harness)
    await harness.tap(USER, AMOUNT)

    await harness.send_text(typed, user_id=USER)

    assert i18n.get("expense-edit-amount-error") in harness.last_text()
    assert (await stored(session_factory))[0] == pytest.approx(12.5)
    await harness.send_text("8", user_id=USER)  # still the amount window
    assert "Amount: <b>8.00 €</b>" in card_lines(harness)


# --- payee ------------------------------------------------------------------------------------


async def test_an_existing_payee_is_picked_from_the_list(harness, make_uow, session_factory):
    await add_manual_expense(make_uow, USER, payee_name="Corner Bakery")
    await entered(harness)

    await harness.tap(USER, PAYEE)
    assert harness.button_texts() == ["✓ Mercadona", "Corner Bakery", TYPE_NAME, BACK]
    await harness.tap(USER, "Corner Bakery")

    assert card_lines(harness)[0] == "💸 <b>Corner Bakery</b>"
    assert card_lines(harness)[-1] == "#corner_bakery"
    assert (
        await one(
            session_factory,
            "select p.name from expenses e join payees p"
            " on p.id = e.payee_id order by e.id desc limit 1",
        )
    ) == ("Corner Bakery",)


async def test_a_typed_payee_reuses_the_same_name_ignoring_case_and_creates_a_new_one(
    harness, session_factory
):
    await entered(harness)

    await harness.tap(USER, PAYEE)
    await harness.tap(USER, TYPE_NAME)
    await harness.send_text("MERCADONA", user_id=USER)
    assert card_lines(harness)[0] == "💸 <b>Mercadona</b>"
    await harness.tap(USER, PAYEE)
    await harness.tap(USER, TYPE_NAME)
    await harness.send_text("Lidl", user_id=USER)

    assert card_lines(harness)[0] == "💸 <b>Lidl</b>"
    async with session_factory() as session:
        names = [r[0] for r in await session.execute(text("select name from payees order by name"))]
    assert names == ["Lidl", "Mercadona"]


async def test_an_empty_payee_name_is_refused(harness):
    await entered(harness)
    await harness.tap(USER, PAYEE)
    await harness.tap(USER, TYPE_NAME)

    await harness.send_text("  ", user_id=USER)

    assert i18n.get("entry-payee-name-error") in harness.last_text()
    assert harness.button_texts() == [BACK]


# --- source -----------------------------------------------------------------------------------


async def test_the_source_window_marks_the_current_one_and_offers_a_new_card(harness, make_uow):
    await add_manual_expense(make_uow, USER, new_card_name="Revolut")
    await entered(harness)

    await harness.tap(USER, SOURCE)

    assert harness.button_texts() == ["✓ Cash", "Revolut", NEW_CARD, BACK]


async def test_a_card_and_cash_can_be_picked(harness, make_uow, session_factory):
    await add_manual_expense(make_uow, USER, new_card_name="Revolut")
    await entered(harness)

    await harness.tap(USER, SOURCE)
    await harness.tap(USER, "Revolut")
    assert "Paid with: Revolut" in card_lines(harness)
    assert (await stored(session_factory))[2] == "Revolut"
    await harness.tap(USER, SOURCE)
    assert harness.button_texts() == ["Cash", "✓ Revolut", NEW_CARD, RENAME, BACK]
    await harness.tap(USER, "Cash")

    assert "Paid with: Cash" in card_lines(harness)


async def test_a_new_card_is_created_and_taken(harness, session_factory):
    await entered(harness)

    await harness.tap(USER, SOURCE)
    await harness.tap(USER, NEW_CARD)
    await harness.send_text("Revolut", user_id=USER)

    assert "Paid with: Revolut" in card_lines(harness)
    assert (await stored(session_factory))[2] == "Revolut"


@pytest.mark.parametrize("name", ["cash", "Cash", " "])
async def test_a_reserved_or_empty_new_card_name_is_refused(harness, name):
    await entered(harness)
    await harness.tap(USER, SOURCE)
    await harness.tap(USER, NEW_CARD)

    await harness.send_text(name, user_id=USER)

    assert i18n.get("entry-new-card-error") in harness.last_text()


async def test_renaming_the_card_renames_it_on_every_expense(harness, make_uow, session_factory):
    await add_manual_expense(make_uow, USER, new_card_name="Revolut")
    await entered(harness)
    await harness.tap(USER, SOURCE)
    await harness.tap(USER, "Revolut")
    await harness.tap(USER, SOURCE)

    await harness.tap(USER, RENAME)
    assert harness.last_text() == i18n.get("expense-edit-rename", name="Revolut")
    await harness.send_text("Monzo", user_id=USER)

    assert "Paid with: Monzo" in card_lines(harness)
    async with session_factory() as session:
        names = [
            r[0]
            for r in await session.execute(
                text(
                    "select s.name from expenses e join payment_sources s"
                    " on s.id = e.payment_source_id order by e.id"
                )
            )
        ]
    assert names == ["Monzo", "Monzo"]


async def test_there_is_no_rename_for_cash(harness):
    await entered(harness)

    await harness.tap(USER, SOURCE)

    assert RENAME not in harness.button_texts()


async def test_a_taken_name_is_refused_when_renaming(harness, make_uow):
    await add_manual_expense(make_uow, USER, new_card_name="Monzo")
    await add_manual_expense(make_uow, USER, new_card_name="Revolut")
    await entered(harness)
    await harness.tap(USER, SOURCE)
    await harness.tap(USER, "Revolut")
    await harness.tap(USER, SOURCE)
    await harness.tap(USER, RENAME)

    await harness.send_text("monzo", user_id=USER)

    assert i18n.get("expense-edit-rename-error") in harness.last_text()
    assert harness.button_texts() == [BACK]


# --- category, date, tags ---------------------------------------------------------------------


async def test_the_category_is_picked_from_the_twelve(harness, session_factory):
    await entered(harness)

    await harness.tap(USER, CATEGORY)
    assert len(harness.button_texts()) == 13
    assert "✓ Groceries" in harness.button_texts()
    await harness.tap(USER, "Rent")

    assert "Category: Rent" in card_lines(harness)
    assert (await stored(session_factory))[3] == "rent"


async def test_yesterday_and_a_typed_date(harness, session_factory):
    await entered(harness)

    await harness.tap(USER, DATE)
    await harness.tap(USER, "Yesterday")
    assert shown(today() - timedelta(days=1)) in card_lines(harness)
    assert (await stored(session_factory))[4] == today() - timedelta(days=1)
    await harness.tap(USER, DATE)
    await harness.tap(USER, OTHER_DATE)
    await harness.send_text("05.01.2026", user_id=USER)

    assert "05.01.2026" in card_lines(harness)
    assert (await stored(session_factory))[4] == date(2026, 1, 5)


@pytest.mark.parametrize("typed", ["31.12.2099", "tomorrow", "30.02"])
async def test_a_future_or_garbage_date_is_refused(harness, session_factory, typed):
    await entered(harness)
    await harness.tap(USER, DATE)
    await harness.tap(USER, OTHER_DATE)

    await harness.send_text(typed, user_id=USER)

    assert i18n.get("entry-date-text-error") in harness.last_text()
    assert (await stored(session_factory))[4] == today()


async def test_tags_are_set_and_cleared(harness, session_factory):
    await entered(harness)

    await harness.tap(USER, TAGS)
    assert harness.button_texts() == [CLEAR, BACK]
    await harness.send_text("Kids, holiday", user_id=USER)
    assert "Tags: #holiday #kids" in card_lines(harness)
    assert (await stored(session_factory))[5] == ["holiday", "kids"]
    await harness.tap(USER, TAGS)
    assert "#holiday #kids" in harness.last_text()
    await harness.tap(USER, CLEAR)

    assert not [line for line in card_lines(harness) if line.startswith("Tags:")]
    assert (await stored(session_factory))[5] == []


async def test_too_many_tags_are_refused(harness):
    await entered(harness)
    await harness.tap(USER, TAGS)

    await harness.send_text(",".join(f"t{i}" for i in range(11)), user_id=USER)

    assert i18n.get("expense-edit-tags-error") in harness.last_text()


async def test_back_returns_to_the_card(harness):
    await entered(harness)
    await harness.tap(USER, CATEGORY)

    await harness.tap(USER, BACK)

    assert harness.button_texts() == CARD_BUTTONS


# --- delete and close -------------------------------------------------------------------------


async def test_delete_asks_first_and_back_keeps_the_expense(harness, session_factory):
    await entered(harness)

    await harness.tap(USER, DELETE)
    assert harness.last_text() == i18n.get("expense-delete-confirm")
    await harness.tap(USER, BACK)

    assert harness.button_texts() == CARD_BUTTONS
    assert (await stored(session_factory))[6] is False


async def test_confirming_deletes_the_expense_and_ends_on_the_deleted_text(
    harness, session_factory
):
    card_id = await entered(harness)
    sent_before = len(harness.sent_messages)

    await harness.tap(USER, DELETE)
    await harness.tap(USER, "🗑 Yes, delete")

    assert (await stored(session_factory))[6] is True
    assert len(harness.sent_messages) == sent_before
    assert harness.last_text() == "🗑 This expense was deleted."
    assert harness.last_keyboard() == (card_id, InlineKeyboardMarkup(inline_keyboard=[]))


async def test_close_hides_the_buttons_and_keeps_the_text(harness):
    card_id = await entered(harness)
    sent_before = len(harness.sent_messages)
    edits = len([c for c in harness.session.calls if isinstance(c, EditMessageText)])

    await harness.tap(USER, CLOSE)

    assert len(harness.sent_messages) == sent_before
    assert harness.last_keyboard() == (card_id, InlineKeyboardMarkup(inline_keyboard=[]))
    assert len([c for c in harness.session.calls if isinstance(c, EditMessageText)]) == edits


async def test_close_does_not_end_the_card_for_a_later_number(harness):
    await entered(harness)
    await harness.tap(USER, CLOSE)

    await harness.send_text("3", user_id=USER)

    assert harness.last_text().startswith("💸 <b>3.00 €</b>")  # a new entry


# --- older cards ------------------------------------------------------------------------------


async def test_a_tap_on_an_older_card_sends_a_fresh_copy_and_keeps_the_old_buttons(harness):
    first = await entered(harness, payee="Mercadona")
    first_markup = harness.last_keyboard()[1]
    second = await entered(harness, amount="3", payee="Lidl")
    assert second != first
    sent_before = len(harness.sent_messages)
    amount = next(
        b.callback_data for row in first_markup.inline_keyboard for b in row if b.text == AMOUNT
    )

    await harness.press(USER, amount, first)

    assert len(harness.sent_messages) == sent_before + 1
    assert "Amount: <b>12.50 €</b>" not in harness.sent_messages[-1].text
    assert harness.sent_messages[-1].text == i18n.get("expense-edit-amount", amount="12.50 €")
    assert not [m for mid, m in harness.keyboards() if mid == first and not m.inline_keyboard]


async def test_close_on_an_older_card_removes_only_its_buttons(harness):
    first = await entered(harness, payee="Mercadona")
    first_markup = harness.last_keyboard()[1]
    second = await entered(harness, amount="3", payee="Lidl")
    close = first_markup.inline_keyboard[-1][0].callback_data

    await harness.press(USER, close, first)

    assert harness.last_keyboard() == (first, InlineKeyboardMarkup(inline_keyboard=[]))
    assert harness.keyboards()[-2][0] == second


async def test_an_old_button_of_a_deleted_expense_alerts_and_loses_its_keyboard(harness):
    card_id = await entered(harness)
    old_data = harness.last_keyboard()[1].inline_keyboard[0][0].callback_data
    await harness.tap(USER, DELETE)
    await harness.tap(USER, "🗑 Yes, delete")
    sent_before = len(harness.sent_messages)

    await harness.press(USER, old_data, card_id)

    alert = harness.session.calls[-2]
    assert isinstance(alert, AnswerCallbackQuery)
    assert (alert.text, alert.show_alert) == (i18n.get("expense-deleted-alert"), True)
    removal = harness.session.calls[-1]
    assert isinstance(removal, EditMessageReplyMarkup)
    assert (removal.message_id, removal.reply_markup) == (card_id, None)
    assert len(harness.sent_messages) == sent_before


async def test_a_pick_on_a_card_deleted_meanwhile_alerts_and_shows_the_deleted_text(
    harness, make_uow, session_factory
):
    await entered(harness)
    await harness.tap(USER, CATEGORY)
    (expense_id,) = await one(session_factory, "select max(id) from expenses")
    await ExpenseService(make_uow).soft_delete(USER, expense_id)

    await harness.tap(USER, "Rent")

    alerts = [c for c in harness.session.calls if isinstance(c, AnswerCallbackQuery) and c.text]
    assert alerts[-1].text == i18n.get("expense-deleted-alert")
    assert harness.last_text() == "🗑 This expense was deleted."
    assert harness.last_keyboard()[1].inline_keyboard == []


# --- history ----------------------------------------------------------------------------------


async def test_a_history_row_of_a_manual_expense_opens_its_card_and_the_history_stays(
    harness, make_uow
):
    await add_manual_expense(make_uow, USER, amount="10.00", spent_at=today())
    await harness.send_text("/expenses", user_id=USER)
    history_id, history_markup = harness.last_keyboard()
    row = harness.button_texts()[0]
    assert row == f"{today().day:02d}.{today().month:02d} Mercadona · 10.00 €"

    await harness.tap(USER, row)

    card = harness.sent_messages[-1]
    assert card.text.startswith("💸 <b>Mercadona</b>")
    assert [b.text for r in card.reply_markup.inline_keyboard for b in r] == CARD_BUTTONS
    assert harness.session.sent_ids[-1] != history_id
    assert not [m for mid, m in harness.keyboards() if mid == history_id and m != history_markup]
    assert not [c for c in harness.session.calls if isinstance(c, EditMessageReplyMarkup)]
    # The card works as any other.
    await harness.tap(USER, CATEGORY)
    assert i18n.get("entry-category") == harness.last_text()


# --- free text never re-sends a card ----------------------------------------------------------


async def test_a_stray_word_with_an_expense_card_open_gets_the_photo_prompt(harness):
    card_id = await entered(harness)
    sent_before = len(harness.sent_messages)

    await harness.send_text("hello", user_id=USER)

    assert harness.last_text() == PHOTO_PROMPT
    assert len(harness.sent_messages) == sent_before + 1
    assert harness.keyboards()[-1][0] == card_id
    assert harness.keyboards()[-1][1].inline_keyboard  # the card keeps its buttons


async def test_a_stray_word_in_a_choice_window_leaves_it_alone(harness):
    await entered(harness)
    await harness.tap(USER, CATEGORY)
    calls_before = len(harness.session.calls)

    await harness.send_text("hello", user_id=USER)

    new_calls = harness.session.calls[calls_before:]
    assert [c.text for c in new_calls] == [PHOTO_PROMPT]
    await harness.tap(USER, "Rent")  # the window still works
    assert "Category: Rent" in card_lines(harness)


async def test_a_stray_word_with_a_receipt_card_open_gets_the_photo_prompt(harness):
    await harness.send_photo(user_id=USER, data=b"jpeg")
    await harness.tasks.drain()
    card_id, markup = harness.last_keyboard()
    sent_before = len(harness.sent_messages)

    await harness.send_text("hello", user_id=USER)

    assert harness.last_text() == PHOTO_PROMPT
    assert len(harness.sent_messages) == sent_before + 1
    assert harness.keyboards()[-1] == (card_id, markup)


async def test_text_typed_in_a_window_that_reads_text_reaches_it(harness):
    await entered(harness)
    await harness.tap(USER, PAYEE)
    await harness.tap(USER, TYPE_NAME)

    await harness.send_text("hello", user_id=USER)

    assert card_lines(harness)[0] == "💸 <b>hello</b>"
    assert PHOTO_PROMPT not in [m.text for m in harness.sent_messages]


async def test_a_new_entry_leaves_the_buttons_of_the_open_card(harness):
    card_id = await entered(harness)
    card_markup = harness.last_keyboard()[1]

    await harness.send_text("3", user_id=USER)

    assert harness.last_text().startswith("💸 <b>3.00 €</b>")
    assert harness.last_keyboard()[0] != card_id
    assert not [m for mid, m in harness.keyboards() if mid == card_id and m != card_markup]
