"""`✏️ Edit` on the receipt card: pick a header field, type or clear its value."""

from datetime import date
from decimal import Decimal

import pytest
from aiogram.methods import AnswerCallbackQuery, EditMessageText
from sqlalchemy import text

from src.bot.i18n import DEFAULT_LOCALE, create_translator_hub
from src.bot.keyboards.receipt import CardWindow, ReceiptCallback
from src.integration.llm import LLMError
from src.services.container import Services
from tests.stubs import fixture, output_of

USER = 7
EDIT = "✏️ Edit"
REPARSE = "🔄 Re-parse"
BACK = "◀ Back"
CLEAR = "🧹 Clear"
DELETE = "🗑 Delete"
FIELDS = [
    "date and time",
    "receipt number",
    "currency",
    "subtotal",
    "total discount",
    "total tax",
    "total",
    "payment method",
    "card brand",
    "card ending",
]

i18n = create_translator_hub().get_translator_by_locale(DEFAULT_LOCALE)
ERROR = i18n.get("issue-input-error", hint="{hint}").split("{hint}")[0]


@pytest.fixture(autouse=True)
async def _allowed(allow_user):
    await allow_user(USER)


@pytest.fixture
def services(make_uow, tmp_storage, harness) -> Services:
    return Services.build(make_uow, storage=tmp_storage, parser=harness.parser)


async def parsed(harness, **kwargs) -> int:
    await harness.send_photo(user_id=USER, **kwargs)
    await harness.tasks.drain()
    return harness.last_keyboard()[0]


async def receipt_ids(session_factory) -> list[int]:
    async with session_factory() as session:
        rows = await session.execute(text("select id from receipts order by id"))
        return [row[0] for row in rows]


async def edit_field(harness, field: str, value: str | None = None) -> None:
    await harness.tap(USER, EDIT)
    await harness.tap(USER, field)
    if value is None:
        await harness.tap(USER, CLEAR)
    else:
        await harness.send_text(value, user_id=USER)


async def expense_of(services, session_factory):
    (receipt_id,) = await receipt_ids(session_factory)
    return await services.expenses.for_receipt(USER, receipt_id)


def rows(harness) -> list[list[str]]:
    return [[b.text for b in row] for row in harness.last_keyboard()[1].inline_keyboard]


# --- the button -----------------------------------------------------------------------------


async def test_a_parsed_card_has_edit_beside_reparse(harness):
    await parsed(harness)

    assert rows(harness)[-2:] == [[EDIT, REPARSE], ["✖ Close"]]


@pytest.mark.parametrize("outcome", ["failed", "not_receipt"])
async def test_a_card_that_is_not_parsed_has_no_edit(harness, outcome):
    if outcome == "failed":
        harness.parser.error = LLMError("timed out")
    else:
        raw = fixture("03")["raw"] | {"is_receipt": False, "items": [], "issues": []}
        harness.parser.default = output_of(raw)

    await parsed(harness)

    assert EDIT not in harness.button_texts()
    assert REPARSE in harness.button_texts()


async def test_a_duplicate_card_has_no_edit(harness):
    await parsed(harness, file_id="a")
    await parsed(harness, file_id="b")

    assert EDIT not in harness.button_texts()


async def test_a_deleted_card_has_no_buttons(harness):
    await parsed(harness)
    await harness.tap(USER, DELETE)
    await harness.tap(USER, "🗑 Yes, delete")

    assert harness.button_texts() == []


async def test_a_stale_edit_alerts_when_the_card_stopped_being_editable(
    harness, services, session_factory
):
    card_id = await parsed(harness)
    (receipt_id,) = await receipt_ids(session_factory)
    data = ReceiptCallback(receipt_id=receipt_id, window=CardWindow.EDIT).pack()
    await services.receipts.soft_delete(USER, receipt_id)

    await harness.press(USER, data, card_id)

    alert = [c for c in harness.session.calls if isinstance(c, AnswerCallbackQuery)][-1]
    assert alert.show_alert


async def test_edit_on_an_older_card_sends_a_fresh_copy(harness):
    first = await parsed(harness, file_id="a")
    raw = fixture("03")["raw"]
    harness.parser.default = output_of(
        raw | {"receipt": raw["receipt"] | {"number": "OTHER"}, "issues": []}
    )
    await parsed(harness, file_id="b")
    first_markup = next(m for mid, m in harness.keyboards() if mid == first)
    edit_data = next(
        b.callback_data for row in first_markup.inline_keyboard for b in row if b.text == EDIT
    )
    sent_before = len(harness.sent_messages)

    await harness.press(USER, edit_data, first)

    assert len(harness.sent_messages) == sent_before + 1
    assert harness.button_texts()[:2] == FIELDS[:2]


# --- the field list and the field screen ----------------------------------------------------


async def test_edit_lists_the_ten_fields_two_per_row(harness):
    card_id = await parsed(harness)
    sent_before = len(harness.sent_messages)

    await harness.tap(USER, EDIT)

    assert harness.button_texts() == [*FIELDS, BACK]
    assert [len(row) for row in rows(harness)] == [2] * 5 + [1]
    assert harness.last_text() == i18n.get("edit-title")
    assert len(harness.sent_messages) == sent_before  # edited in place
    assert harness.last_keyboard()[0] == card_id


async def test_back_from_the_list_returns_to_the_card(harness):
    await parsed(harness)
    await harness.tap(USER, EDIT)

    await harness.tap(USER, BACK)

    assert rows(harness)[-2:] == [[EDIT, REPARSE], ["✖ Close"]]


async def test_a_field_screen_shows_the_current_value_and_the_hint(harness):
    await parsed(harness)
    await harness.tap(USER, EDIT)

    await harness.tap(USER, "card ending")

    assert "Enter the card ending (four digits)" in harness.last_text()
    assert "Current value:</b> 0848" in harness.last_text()
    assert harness.button_texts() == [CLEAR, BACK]


async def test_an_empty_field_says_not_specified(harness):
    raw = fixture("03")["raw"]
    harness.parser.default = output_of(raw | {"payment": raw["payment"] | {"card_last4": None}})
    await parsed(harness)
    await harness.tap(USER, EDIT)

    await harness.tap(USER, "card ending")

    assert "Current value:</b> not specified" in harness.last_text()


async def test_back_from_a_field_returns_to_the_list(harness):
    await parsed(harness)
    await harness.tap(USER, EDIT)
    await harness.tap(USER, "total")

    await harness.tap(USER, BACK)

    assert harness.button_texts() == [*FIELDS, BACK]


# --- writing a value ------------------------------------------------------------------------


async def test_a_card_ending_shows_on_the_card_and_moves_the_expense_to_that_card(
    harness, services, session_factory
):
    card_id = await parsed(harness)
    sent_before = len(harness.sent_messages)

    await edit_field(harness, "card ending", "1234")

    assert "card VISA •1234" in harness.last_text()
    assert len(harness.sent_messages) == sent_before  # the card is edited in place
    assert harness.last_keyboard()[0] == card_id
    assert rows(harness)[-2:] == [[EDIT, REPARSE], ["✖ Close"]]
    assert "VISA" in (await expense_of(services, session_factory)).payment_source_name
    assert "1234" in (await expense_of(services, session_factory)).payment_source_name


async def test_clearing_the_card_ending_moves_the_expense_to_cash(
    harness, services, session_factory
):
    await parsed(harness)

    await edit_field(harness, "card ending")  # Clear

    assert "•0848" not in harness.last_text()
    assert (await expense_of(services, session_factory)).payment_source_name == "Cash"


async def test_a_total_changes_the_expense_amount(harness, services, session_factory):
    await parsed(harness)

    await edit_field(harness, "total", "9,99")

    assert "9.99 €" in harness.last_text()
    assert (await expense_of(services, session_factory)).amount == Decimal("9.99")


async def test_a_date_changes_the_expense_day(harness, services, session_factory):
    await parsed(harness)

    await edit_field(harness, "date and time", "05.10.2026 18:30")

    assert "05.10.2026 18:30" in harness.last_text()
    assert (await expense_of(services, session_factory)).spent_at == date(2026, 10, 5)


async def test_a_currency_changes_the_expense_currency(harness, services, session_factory):
    await parsed(harness)

    await edit_field(harness, "currency", "usd")

    assert (await expense_of(services, session_factory)).currency == "USD"


async def test_a_text_field_can_be_set_and_cleared(harness):
    await parsed(harness)

    await edit_field(harness, "receipt number", "AB-1")
    await harness.tap(USER, EDIT)
    await harness.tap(USER, "receipt number")
    assert "Current value:</b> AB-1" in harness.last_text()

    await harness.tap(USER, CLEAR)
    await harness.tap(USER, EDIT)
    await harness.tap(USER, "receipt number")
    assert "Current value:</b> not specified" in harness.last_text()


# --- refusals -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("card ending", "12"),
        ("total", "abc"),
        ("date and time", "yesterday"),
        ("currency", "euro"),
    ],
)
async def test_a_bad_value_keeps_the_field_screen_with_the_error(harness, field, value):
    await parsed(harness)
    await harness.tap(USER, EDIT)
    await harness.tap(USER, field)

    await harness.send_text(value, user_id=USER)

    assert ERROR in harness.last_text()
    assert harness.button_texts() == [CLEAR, BACK]


async def test_a_number_typed_on_the_field_screen_is_the_value_not_an_entry(
    harness, services, session_factory
):
    await parsed(harness)
    await harness.tap(USER, EDIT)
    await harness.tap(USER, "total")
    sent_before = len(harness.sent_messages)

    await harness.send_text("12.50", user_id=USER)

    assert len(harness.sent_messages) == sent_before  # no entry prompt, no hint
    assert (await expense_of(services, session_factory)).amount == Decimal("12.50")
    assert "12.50 €" in harness.last_text()
    assert [c for c in harness.session.calls if isinstance(c, EditMessageText)]


async def test_back_clears_the_error_line(harness):
    await parsed(harness)
    await harness.tap(USER, EDIT)
    await harness.tap(USER, "total")
    await harness.send_text("abc", user_id=USER)
    await harness.tap(USER, BACK)

    await harness.tap(USER, "total")

    assert ERROR not in harness.last_text()


# --- surviving a re-parse -------------------------------------------------------------------


async def test_the_edit_survives_a_reparse(harness, services, session_factory):
    await parsed(harness)
    await edit_field(harness, "card ending", "1234")
    (receipt_id,) = await receipt_ids(session_factory)

    await services.receipts.parse(USER, receipt_id)  # the stub returns the old 0848

    card = await services.receipts.card(USER, receipt_id)
    assert card.card_last4 == "1234"
    assert "1234" in (await services.expenses.for_receipt(USER, receipt_id)).payment_source_name


# --- an edit answers the open issue on its field -------------------------------------------

CARD_ISSUE = {
    "type": "other",
    "severity": "high",
    "field": "payment.card_last4",
    "item_name_raw": None,
    "message": "Unseen card ending.",
}
REVIEW = "⚠️ Review (1)"


async def parsed_with_card_issue(harness) -> None:
    raw = fixture("03")["raw"]
    harness.parser.default = output_of(raw | {"issues": [CARD_ISSUE]})
    await parsed(harness)


async def test_an_edit_of_the_field_with_an_issue_drops_the_review(harness):
    await parsed_with_card_issue(harness)
    assert REVIEW in harness.button_texts()

    await edit_field(harness, "card ending", "4321")

    assert "•4321" in harness.last_text()
    assert not any(t.startswith("⚠️ Review") for t in harness.button_texts())


async def test_the_review_walk_no_longer_offers_the_answered_issue(harness):
    raw = fixture("03")["raw"]
    other = CARD_ISSUE | {"field": "totals.total", "message": "The total looks odd."}
    harness.parser.default = output_of(raw | {"issues": [CARD_ISSUE, other]})
    await parsed(harness)

    await edit_field(harness, "card ending", "4321")
    await harness.tap(USER, REVIEW)

    assert "The total looks odd." in harness.last_text()
    assert "Unseen card ending." not in harness.last_text()


async def test_clearing_the_field_with_an_issue_drops_the_review(harness):
    await parsed_with_card_issue(harness)

    await edit_field(harness, "card ending")

    assert not any(t.startswith("⚠️ Review") for t in harness.button_texts())


async def test_an_edit_of_a_field_without_an_issue_keeps_the_review(harness):
    await parsed_with_card_issue(harness)

    await edit_field(harness, "total", "9.99")

    assert REVIEW in harness.button_texts()
