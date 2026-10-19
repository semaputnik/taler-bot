"""The manual entry: a bare number starts `ExpenseEntry`, five short steps, one saved expense."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from aiogram.methods import DeleteMessage
from sqlalchemy import text

from src.bot.handlers.dialog import text_input_states
from src.bot.i18n import DEFAULT_LOCALE, create_translator_hub
from tests.helpers import add_manual_expense

USER = 7
BACK = "◀ Back"
TYPE_NAME = "✏️ Type a name"
NEW_CARD = "➕ New card"
CASH = "Cash"
OTHER_DATE = "✏️ Other date"
SKIP = "⏭ Skip"
PHOTO_PROMPT = "Send me a photo of a receipt."

i18n = create_translator_hub().get_translator_by_locale(DEFAULT_LOCALE)


def today() -> date:
    return datetime.now(ZoneInfo("Europe/Madrid")).date()


@pytest.fixture(autouse=True)
async def _allowed(allow_user):
    await allow_user(USER)


async def rows(session_factory, sql: str) -> list[tuple]:
    async with session_factory() as session:
        return [tuple(row) for row in await session.execute(text(sql))]


async def expenses(session_factory) -> list[tuple]:
    return await rows(
        session_factory,
        "select e.amount, e.currency, e.spent_at, e.category, p.name, s.name,"
        " coalesce((select array_agg(t.name order by t.name) from expense_tags et"
        " join tags t on t.id = et.tag_id where et.expense_id = e.id), '{}'), e.receipt_id"
        " from expenses e left join payees p on p.id = e.payee_id"
        " left join payment_sources s on s.id = e.payment_source_id order by e.id",
    )


async def to_source(harness, payee: str = "Mercadona", amount: str = "12.50") -> None:
    await harness.send_text(amount, user_id=USER)
    await harness.tap(USER, TYPE_NAME)
    await harness.send_text(payee, user_id=USER)


async def to_category(harness, source: str = CASH, **kwargs) -> None:
    await to_source(harness, **kwargs)
    await harness.tap(USER, source)


async def to_date(harness, category: str = "Groceries") -> None:
    await to_category(harness)
    await harness.tap(USER, category)


async def to_tags(harness, day: str = "Today") -> None:
    await to_date(harness)
    await harness.tap(USER, day)


# --- the start ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("typed", "shown"), [("12.50", "12.50 €"), ("12,50", "12.50 €"), ("7", "7.00 €")]
)
async def test_an_amount_starts_the_entry(harness, typed, shown):
    await harness.send_text(typed, user_id=USER)

    assert harness.last_text() == f"<b>{shown}</b>\n\n{i18n.get('entry-payee')}"


@pytest.mark.parametrize("typed", ["hello", "12.345", "0", "0.00", "-5", "12.50 eur", "123456789"])
async def test_other_text_is_not_an_amount(harness, session_factory, typed):
    await harness.send_text(typed, user_id=USER)

    assert harness.last_text() == PHOTO_PROMPT
    assert await expenses(session_factory) == []


async def test_a_stranger_gets_no_reply(harness):
    await harness.send_text("12.50", user_id=99)

    assert harness.session.calls == []


async def test_a_number_starts_an_entry_while_a_receipt_card_is_open(harness, session_factory):
    await harness.send_photo(user_id=USER, data=b"jpeg")
    await harness.tasks.drain()

    await harness.send_text("15", user_id=USER)

    assert harness.last_text().startswith("<b>15.00 €</b>")


async def test_a_number_typed_in_an_input_step_is_its_input_not_a_new_entry(harness):
    await to_tags(harness)

    await harness.send_text("2026", user_id=USER)

    assert "#2026" in harness.sent_messages[-1].text
    assert harness.sent_messages[-1].text.startswith("<b>Mercadona</b>")


async def test_a_number_in_a_choice_step_restarts_the_entry_with_the_new_amount(harness):
    await to_category(harness)

    await harness.send_text("3", user_id=USER)

    assert harness.last_text() == f"<b>3.00 €</b>\n\n{i18n.get('entry-payee')}"


async def test_a_stray_word_in_the_payee_name_step_is_the_name(harness):
    await harness.send_text("12.50", user_id=USER)
    await harness.tap(USER, TYPE_NAME)

    await harness.send_text("hello", user_id=USER)

    assert i18n.get("entry-source") in harness.last_text()
    assert PHOTO_PROMPT not in [m.text for m in harness.sent_messages]


def test_the_steps_that_read_typed_text_are_known():
    assert {state.state for state in text_input_states()} == {
        "ExpenseEntrySG:payee_name",
        "ExpenseEntrySG:new_card",
        "ExpenseEntrySG:date_text",
        "ExpenseEntrySG:tags",
        "ExpenseCardSG:amount",
        "ExpenseCardSG:payee_name",
        "ExpenseCardSG:new_card",
        "ExpenseCardSG:source_rename",
        "ExpenseCardSG:date_text",
        "ExpenseCardSG:tags",
        "ReceiptCardSG:item_input",
        "ReceiptCardSG:tags",
        "ReceiptCardSG:issue_input",
        "ReceiptCardSG:issue_rename",
    }


async def test_the_greeting_tells_about_the_entry(harness):
    await harness.send_text("/start", user_id=USER)

    assert "Send an amount like 12.50 to record an expense." in harness.last_text()


# --- payee ----------------------------------------------------------------------------------


async def test_the_payee_step_offers_the_five_most_recent_payees_and_typing(harness, make_uow):
    for days, name in enumerate(["One", "Two", "Three", "Four", "Five", "Six"]):
        await add_manual_expense(
            make_uow, USER, payee_name=name, spent_at=today() - timedelta(days=days)
        )

    await harness.send_text("12.50", user_id=USER)

    assert harness.button_texts() == ["One", "Two", "Three", "Four", "Five", TYPE_NAME]


async def test_picking_a_payee_goes_on_to_the_source(harness, make_uow):
    await add_manual_expense(make_uow, USER, payee_name="Mercadona")
    await harness.send_text("12.50", user_id=USER)

    await harness.tap(USER, "Mercadona")

    assert i18n.get("entry-source") in harness.last_text()
    assert harness.button_texts() == [CASH, NEW_CARD, BACK]


async def test_a_typed_name_reuses_a_payee_ignoring_case_and_creates_a_new_one(
    harness, make_uow, session_factory
):
    await add_manual_expense(make_uow, USER, payee_name="Mercadona")
    await to_category(harness, payee="MERCADONA")
    await harness.tap(USER, "Groceries")
    await harness.tap(USER, "Today")
    await harness.tap(USER, SKIP)
    await to_category(harness, payee="Corner Bakery")
    await harness.tap(USER, "Groceries")
    await harness.tap(USER, "Today")
    await harness.tap(USER, SKIP)

    assert await rows(session_factory, "select name from payees order by name") == [
        ("Corner Bakery",),
        ("Mercadona",),
    ]
    assert [row[4] for row in await expenses(session_factory)] == [
        "Mercadona",
        "Mercadona",
        "Corner Bakery",
    ]


async def test_an_empty_name_is_refused_and_a_number_is_a_name(harness):
    await harness.send_text("12.50", user_id=USER)
    await harness.tap(USER, TYPE_NAME)

    await harness.send_text("   ", user_id=USER)
    assert i18n.get("entry-payee-name-error") in harness.last_text()
    await harness.send_text("5", user_id=USER)

    assert i18n.get("entry-source") in harness.last_text()
    assert "12.50 €" in harness.last_text()  # the amount stayed: 5 was not a new entry


# --- source ---------------------------------------------------------------------------------


async def test_the_source_step_lists_cash_the_cards_and_a_new_card(harness, make_uow):
    await add_manual_expense(make_uow, USER, new_card_name="Revolut")
    await to_source(harness)

    assert harness.button_texts() == [CASH, "Revolut", NEW_CARD, BACK]


async def test_an_existing_card_is_the_source(harness, make_uow, session_factory):
    await add_manual_expense(make_uow, USER, new_card_name="Revolut")
    await to_category(harness, source="Revolut")
    await harness.tap(USER, "Groceries")
    await harness.tap(USER, "Today")
    await harness.tap(USER, SKIP)

    assert (await expenses(session_factory))[-1][5] == "Revolut"
    assert await rows(session_factory, "select count(*) from payment_sources") == [(1,)]


async def test_a_new_card_is_created_with_the_expense(harness, session_factory):
    await to_source(harness)
    await harness.tap(USER, NEW_CARD)

    assert i18n.get("entry-new-card") in harness.last_text()
    await harness.send_text("Revolut", user_id=USER)
    await harness.tap(USER, "Groceries")
    await harness.tap(USER, "Today")
    await harness.tap(USER, SKIP)

    assert (await expenses(session_factory))[0][5] == "Revolut"
    assert await rows(session_factory, "select kind, last4 from payment_sources") == [
        ("card", None)
    ]


@pytest.mark.parametrize("name", ["revolut", "REVOLUT ", "cash", " ", "Cash"])
async def test_a_taken_or_reserved_card_name_is_refused(harness, make_uow, name):
    await add_manual_expense(make_uow, USER, new_card_name="Revolut")
    await to_source(harness)
    await harness.tap(USER, NEW_CARD)

    await harness.send_text(name, user_id=USER)

    assert i18n.get("entry-new-card-error") in harness.last_text()
    assert harness.button_texts() == [BACK]


# --- category and date ----------------------------------------------------------------------


async def test_the_category_step_lists_the_twelve_two_per_row(harness):
    await to_category(harness)

    texts = harness.button_texts()
    assert len(texts) == 13 and texts[0] == "Groceries" and texts[-1] == BACK
    assert [len(r) for r in harness.last_keyboard()[1].inline_keyboard] == [2] * 6 + [1]
    assert i18n.get("entry-category") in harness.last_text()


async def test_the_date_step_has_today_yesterday_and_other(harness):
    await to_date(harness)

    assert harness.button_texts() == ["Today", "Yesterday", OTHER_DATE, BACK]


@pytest.mark.parametrize(("button", "days"), [("Today", 0), ("Yesterday", 1)])
async def test_today_and_yesterday(harness, session_factory, button, days):
    await to_tags(harness, button)
    await harness.tap(USER, SKIP)

    assert (await expenses(session_factory))[0][2] == today() - timedelta(days=days)


async def test_a_typed_date_in_this_year_or_with_a_year(harness, session_factory):
    day = today() - timedelta(days=3)
    await to_date(harness)
    await harness.tap(USER, OTHER_DATE)
    assert i18n.get("entry-date-text") in harness.last_text()
    await harness.send_text(day.strftime("%d.%m.%Y"), user_id=USER)
    await harness.tap(USER, SKIP)
    await to_date(harness)
    await harness.tap(USER, OTHER_DATE)
    await harness.send_text("05.03.2020", user_id=USER)
    await harness.tap(USER, SKIP)

    assert [row[2] for row in await expenses(session_factory)] == [day, date(2020, 3, 5)]


@pytest.mark.parametrize("typed", ["tomorrow", "31.02", "01.01.2999", ""])
async def test_a_future_or_garbage_date_is_refused_with_a_hint(harness, session_factory, typed):
    await to_date(harness)
    await harness.tap(USER, OTHER_DATE)

    await harness.send_text(typed or " ", user_id=USER)

    assert i18n.get("entry-date-text-error") in harness.last_text()
    assert harness.button_texts() == [BACK]
    assert await expenses(session_factory) == []


# --- tags and the result --------------------------------------------------------------------


async def test_typed_tags_are_saved_normalised_and_the_expense_card_is_sent(
    harness, session_factory
):
    await to_tags(harness)
    assert i18n.get("entry-tags") in harness.last_text()
    assert harness.button_texts() == [SKIP, BACK]

    await harness.send_text("Kids, holiday ,kids", user_id=USER)

    assert await expenses(session_factory) == [
        (
            pytest.approx(12.5),
            "EUR",
            today(),
            "groceries",
            "Mercadona",
            "Cash",
            ["holiday", "kids"],
            None,
        )
    ]
    sent = harness.sent_messages[-1]
    assert sent.parse_mode == "HTML"
    assert [b.text for row in sent.reply_markup.inline_keyboard for b in row] == [
        "✏️ Amount",
        "🏪 Payee",
        "💳 Source",
        "🏷 Category",
        "📅 Date",
        "#️⃣ Tags",
        "🗑 Delete",
        "✖ Close",
    ]
    assert sent.text.splitlines() == [
        "<b>Mercadona</b>",
        "",
        today().strftime("%d.%m.%Y"),
        "Amount: <b>12.50 €</b>",
        "Paid with: Cash",
        "Category: Groceries",
        "Tags: #holiday #kids",
        "",
        "#mercadona",
    ]


async def test_skipping_the_tags_saves_none(harness, session_factory):
    await to_tags(harness)

    await harness.tap(USER, SKIP)

    assert (await expenses(session_factory))[0][6] == []
    assert "Tags" not in harness.sent_messages[-1].text


async def test_too_many_tags_are_refused_and_nothing_is_saved(harness, session_factory):
    await to_tags(harness)

    await harness.send_text(",".join(f"t{i}" for i in range(11)), user_id=USER)

    assert i18n.get("entry-tags-error") in harness.last_text()
    assert await expenses(session_factory) == []
    await harness.send_text("ok", user_id=USER)
    assert [row[6] for row in await expenses(session_factory)] == [["ok"]]


async def test_a_payee_name_without_letters_goes_back_to_its_step_at_the_end(
    harness, session_factory
):
    await to_source(harness, payee="!!!")
    await harness.tap(USER, CASH)
    await harness.tap(USER, "Groceries")
    await harness.tap(USER, "Today")

    await harness.tap(USER, SKIP)

    assert i18n.get("entry-payee-name-error") in harness.last_text()
    assert await expenses(session_factory) == []


async def test_the_entry_ends_and_a_second_number_starts_a_new_one(harness):
    await to_tags(harness)
    await harness.tap(USER, SKIP)

    await harness.send_text("3", user_id=USER)

    assert harness.last_text().startswith("<b>3.00 €</b>")


# --- back and abandoning --------------------------------------------------------------------


async def test_back_returns_one_step_from_every_step_and_saves_nothing(harness, session_factory):
    await harness.send_text("12.50", user_id=USER)
    await harness.tap(USER, TYPE_NAME)
    await harness.tap(USER, BACK)
    assert i18n.get("entry-payee") in harness.last_text()  # payee_name -> payee
    await harness.tap(USER, TYPE_NAME)
    await harness.send_text("Mercadona", user_id=USER)
    await harness.tap(USER, NEW_CARD)
    await harness.tap(USER, BACK)
    assert i18n.get("entry-source") in harness.last_text()  # new_card -> source
    await harness.tap(USER, CASH)
    await harness.tap(USER, BACK)
    assert i18n.get("entry-source") in harness.last_text()  # category -> source
    await harness.tap(USER, BACK)
    assert i18n.get("entry-payee") in harness.last_text()  # source -> payee
    await harness.tap(USER, TYPE_NAME)
    await harness.send_text("Mercadona", user_id=USER)
    assert "✓ Cash" in harness.button_texts()  # the earlier answer is marked
    await harness.tap(USER, "✓ Cash")
    await harness.tap(USER, "Groceries")
    await harness.tap(USER, BACK)
    assert i18n.get("entry-category") in harness.last_text()  # date -> category
    await harness.tap(USER, "✓ Groceries")
    await harness.tap(USER, OTHER_DATE)
    await harness.tap(USER, BACK)
    assert i18n.get("entry-date") in harness.last_text()  # date_text -> date
    await harness.tap(USER, "Today")
    await harness.tap(USER, BACK)
    assert i18n.get("entry-date") in harness.last_text()  # tags -> date

    assert await expenses(session_factory) == []


async def test_going_back_and_choosing_again_replaces_the_answer(
    harness, make_uow, session_factory
):
    await add_manual_expense(make_uow, USER, payee_name="Lidl")
    await to_source(harness, payee="Mercadona")
    await harness.tap(USER, BACK)
    await harness.tap(USER, "Lidl")
    await harness.tap(USER, CASH)
    await harness.tap(USER, "Groceries")
    await harness.tap(USER, "Today")
    await harness.tap(USER, SKIP)

    assert (await expenses(session_factory))[-1][4] == "Lidl"
    assert await rows(session_factory, "select count(*) from payees") == [(1,)]


async def test_a_photo_sent_mid_entry_is_saved_and_the_entry_message_stays(
    harness, session_factory
):
    await to_category(harness)
    entry_message = harness.last_keyboard()[0]
    deleted = len([c for c in harness.session.calls if isinstance(c, DeleteMessage)])

    await harness.send_photo(user_id=USER, data=b"jpeg")
    await harness.tasks.drain()

    assert await rows(session_factory, "select count(*) from receipts") == [(1,)]
    assert len([c for c in harness.session.calls if isinstance(c, DeleteMessage)]) == deleted
    assert entry_message in [m for m, _ in harness.keyboards()]
    assert all(row[7] is not None for row in await expenses(session_factory))


# --- the rest of the bot sees the expense ---------------------------------------------------


async def test_the_manual_expense_is_in_receipts_and_in_stats(harness):
    await to_tags(harness)
    await harness.send_text("holiday", user_id=USER)

    await harness.send_text("/expenses", user_id=USER)
    # The month counts it; its row opens a card, which arrives with the expense card dialog.
    assert i18n.get("history-summary", count=1, totals="12.50 €") in harness.last_text()
    await harness.send_text("/stats", user_id=USER)
    assert "12.50" in harness.last_text()
    assert "Groceries" in harness.last_text()
