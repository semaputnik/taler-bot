"""The ReceiptCard dialog (delete flow) through the real dispatcher on real Postgres."""

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import AnswerCallbackQuery, EditMessageReplyMarkup, EditMessageText
from sqlalchemy import text

from src.bot.i18n import DEFAULT_LOCALE, create_translator_hub
from src.domain.enums import Category
from src.integration.llm import LLMError
from tests.stubs import fixture, output_of

USER = 7
PHOTO = "🖼 Photo"
DELETE = "🗑 Delete"
ITEMS = "📋 Items"

i18n = create_translator_hub().get_translator_by_locale(DEFAULT_LOCALE)


@pytest.fixture(autouse=True)
async def _allowed(allow_user):
    await allow_user(USER)


async def deleted_flags(session_factory) -> list[bool]:
    async with session_factory() as session:
        rows = await session.execute(
            text("select deleted_at is not null from receipts order by id")
        )
        return [row[0] for row in rows]


def stored_files(storage) -> list[str]:
    root = storage._root
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


async def parsed(harness, **kwargs) -> int:
    """Send a photo, wait for the reply; return the summary's message id."""
    await harness.send_photo(user_id=USER, **kwargs)
    await harness.tasks.drain()
    return harness.last_keyboard()[0]


def last_text(harness) -> str:
    """The text of the latest message the dialog sent or edited."""
    for call in reversed(harness.session.calls):
        if isinstance(call, EditMessageText):
            return call.text
        if call in harness.sent_messages:
            return call.text
    raise AssertionError("nothing sent")


async def test_the_parse_reply_carries_photo_and_delete_buttons(harness):
    await parsed(harness)

    assert harness.button_texts() == [ITEMS, PHOTO, DELETE]


@pytest.mark.parametrize("outcome", ["not_receipt", "failed"])
async def test_every_parse_outcome_carries_the_keyboard(harness, outcome):
    if outcome == "failed":
        harness.parser.error = LLMError("timed out")
    else:
        raw = fixture("03")["raw"] | {"is_receipt": False, "items": [], "issues": []}
        harness.parser.default = output_of(raw)

    await parsed(harness)

    assert harness.button_texts() == [PHOTO, DELETE]


async def test_the_duplicate_reply_carries_the_keyboard(harness):
    await parsed(harness, file_id="a")
    await parsed(harness, file_id="b")

    assert harness.sent_messages[-1].text.startswith("♻️")
    assert harness.button_texts() == [PHOTO, DELETE]


async def test_delete_opens_a_confirmation_as_a_new_message(harness):
    summary_id = await parsed(harness)
    sent_before = len(harness.sent_messages)

    await harness.tap(USER, DELETE)

    assert len(harness.sent_messages) == sent_before + 1
    assert harness.sent_messages[-1].text == i18n.get("card-delete-confirm")
    assert harness.button_texts() == ["🗑 Yes, delete", "◀ Back"]
    assert harness.last_keyboard()[0] != summary_id
    # the summary itself is never edited
    assert not [c for c in harness.session.calls if isinstance(c, EditMessageText)]


async def test_back_returns_to_the_card(harness):
    await parsed(harness)
    await harness.tap(USER, DELETE)

    await harness.tap(USER, "◀ Back")

    assert "Consum" in last_text(harness)
    assert harness.button_texts() == [ITEMS, PHOTO, DELETE, "✖ Close"]


async def test_confirming_deletes_the_receipt_and_trashes_the_photo(
    harness, session_factory, tmp_storage
):
    await parsed(harness)
    (path,) = stored_files(tmp_storage)
    await harness.tap(USER, DELETE)

    await harness.tap(USER, "🗑 Yes, delete")

    assert await deleted_flags(session_factory) == [True]
    assert stored_files(tmp_storage) == [f".trash/{path}"]
    assert harness.sent_messages[-1].text == i18n.get("card-deleted-done")


async def test_close_ends_the_dialog_and_keeps_the_receipt(harness, session_factory):
    await parsed(harness)
    await harness.tap(USER, DELETE)
    await harness.tap(USER, "◀ Back")

    await harness.tap(USER, "✖ Close")

    assert harness.last_keyboard()[1].inline_keyboard == []
    assert await deleted_flags(session_factory) == [False]


async def test_an_old_button_of_a_deleted_receipt_alerts_and_loses_its_keyboard(harness):
    summary_id = await parsed(harness)
    summary_data = harness.last_keyboard()[1].inline_keyboard[0][0].callback_data
    await harness.tap(USER, DELETE)
    await harness.tap(USER, "🗑 Yes, delete")
    sent_before = len(harness.sent_messages)

    await harness.press(USER, summary_data, summary_id)

    alert = harness.session.calls[-2]
    assert isinstance(alert, AnswerCallbackQuery)
    assert (alert.text, alert.show_alert) == (i18n.get("card-deleted-alert"), True)
    removal = harness.session.calls[-1]
    assert isinstance(removal, EditMessageReplyMarkup)
    assert (removal.message_id, removal.reply_markup) == (summary_id, None)
    assert len(harness.sent_messages) == sent_before


async def test_a_vanished_summary_message_is_tolerated(harness, monkeypatch):
    summary_id = await parsed(harness)
    data = harness.last_keyboard()[1].inline_keyboard[0][0].callback_data
    await harness.tap(USER, DELETE)
    await harness.tap(USER, "🗑 Yes, delete")

    async def gone(*args, **kwargs):
        raise TelegramBadRequest(
            method=EditMessageReplyMarkup(chat_id=1, message_id=1),
            message="Bad Request: message to edit not found",
        )

    monkeypatch.setattr(harness.bot, "edit_message_reply_markup", gone)

    await harness.press(USER, data, summary_id)  # must not raise


async def test_a_stranger_is_dropped_silently(harness, session_factory):
    await parsed(harness)
    data = harness.last_keyboard()[1].inline_keyboard[0][0].callback_data
    calls_before = len(harness.session.calls)

    await harness.press(999, data, 5)

    assert len(harness.session.calls) == calls_before
    assert await deleted_flags(session_factory) == [False]


async def test_a_photo_sent_while_the_card_is_open_is_still_saved(harness, session_factory):
    await parsed(harness, file_id="a")
    await harness.tap(USER, DELETE)

    await harness.send_photo(user_id=USER, file_id="b")
    await harness.tasks.drain()

    assert [m.text for m in harness.sent_messages].count(i18n.get("receipt-saved")) == 2
    async with session_factory() as session:
        count = (await session.execute(text("select count(*) from receipts"))).scalar_one()
    assert count == 2


async def test_a_failed_receipt_card_shows_its_status(harness):
    harness.parser.error = LLMError("timed out")
    await parsed(harness)
    await harness.tap(USER, DELETE)

    await harness.tap(USER, "◀ Back")

    body = last_text(harness)
    assert i18n.get("card-status-failed") in body
    assert "Photo received:" in body


async def test_a_duplicate_card_names_the_receipt_it_repeats(harness):
    await parsed(harness, file_id="a")
    await parsed(harness, file_id="b")
    await harness.tap(USER, DELETE)

    await harness.tap(USER, "◀ Back")

    body = last_text(harness)
    assert i18n.get("card-status-duplicate") in body
    assert "Repeats <b>Consum" in body
    assert "7.58 EUR" in body


async def test_a_receipt_that_is_being_read_cannot_be_deleted(harness, session_factory):
    await parsed(harness)
    await harness.tap(USER, DELETE)
    # Leave the receipt the way a running parse would.
    async with session_factory() as session:
        await session.execute(text("update receipts set status = 'parsing'"))
        await session.commit()

    await harness.tap(USER, "🗑 Yes, delete")

    alerts = [c for c in harness.session.calls if isinstance(c, AnswerCallbackQuery) and c.text]
    assert [(a.text, a.show_alert) for a in alerts] == [
        (i18n.get("card-cannot-delete-parsing"), True)
    ]
    assert await deleted_flags(session_factory) == [False]


# --- items ---------------------------------------------------------------------------------

PELLEGRINO = "Aigua amb gas Pellegrino · 2 pcs · 2.78"
FREE_LIMO = "Cervesa Free Limo · 6 pcs · 4.80"


def many_items(count: int, *, number: str = "N1") -> dict:
    """The fixture receipt with `count` distinct items (the lines no longer add up: fine)."""
    raw = fixture("03")["raw"]
    items = [
        raw["items"][0] | {"name_raw": f"ITEM {i}", "name_normalized": f"Item {i}"}
        for i in range(count)
    ]
    return raw | {"items": items, "receipt": raw["receipt"] | {"number": number}}


async def test_a_receipt_without_items_has_no_items_button(harness):
    raw = fixture("03")["raw"] | {"items": [], "issues": []}
    harness.parser.default = output_of(raw)

    await parsed(harness)

    assert harness.button_texts() == [PHOTO, DELETE]


async def test_the_card_of_a_receipt_without_items_has_no_items_button(harness):
    raw = fixture("03")["raw"] | {"items": [], "issues": []}
    harness.parser.default = output_of(raw)
    await parsed(harness)
    await harness.tap(USER, DELETE)

    await harness.tap(USER, "◀ Back")

    assert harness.button_texts() == [PHOTO, DELETE, "✖ Close"]


async def test_items_opens_the_list_as_a_new_message(harness):
    summary_id = await parsed(harness)
    sent_before = len(harness.sent_messages)

    await harness.tap(USER, ITEMS)

    assert len(harness.sent_messages) == sent_before + 1
    assert harness.sent_messages[-1].text == i18n.get("card-items-title", count="2")
    assert harness.last_keyboard()[0] != summary_id
    assert harness.button_texts() == [PELLEGRINO, FREE_LIMO, "◀ Back"]


async def test_a_row_tap_shows_the_item_details(harness):
    await parsed(harness)
    await harness.tap(USER, ITEMS)

    await harness.tap(USER, FREE_LIMO)

    body = last_text(harness)
    assert "<b>Cervesa Free Limo</b>" in body
    assert "CERV FREE LIMO." in body
    assert "Drinks" in body
    assert "6 pcs" in body
    assert "0.80" in body
    assert "4.80" in body
    assert "21%" in body
    assert "Discount" not in body  # zero discount is hidden
    assert harness.button_texts() == ["◀ Back"]


async def test_back_goes_from_the_item_to_the_list_and_then_to_the_card(harness):
    await parsed(harness)
    await harness.tap(USER, ITEMS)
    await harness.tap(USER, PELLEGRINO)

    await harness.tap(USER, "◀ Back")
    assert harness.button_texts() == [PELLEGRINO, FREE_LIMO, "◀ Back"]

    await harness.tap(USER, "◀ Back")
    assert "Consum" in last_text(harness)
    assert harness.button_texts() == [ITEMS, PHOTO, DELETE, "✖ Close"]


async def test_a_long_list_is_paged_by_eight(harness):
    harness.parser.default = output_of(many_items(12))
    await parsed(harness)

    await harness.tap(USER, ITEMS)

    rows = [t for t in harness.button_texts() if t.startswith("Item ")]
    assert len(rows) == 8
    assert rows[0].startswith("Item 0 ·")
    assert harness.button_texts()[-2:] == ["2", "◀ Back"]

    await harness.tap(USER, ">")

    rows = [t for t in harness.button_texts() if t.startswith("Item ")]
    assert [r.split(" ·")[0] for r in rows] == ["Item 8", "Item 9", "Item 10", "Item 11"]


async def test_a_tap_on_the_second_page_opens_that_item(harness):
    harness.parser.default = output_of(many_items(12))
    await parsed(harness)
    await harness.tap(USER, ITEMS)
    await harness.tap(USER, ">")

    await harness.tap(USER, "Item 10 · 2 pcs · 2.78")

    assert "<b>Item 10</b>" in last_text(harness)


async def test_a_discount_and_unknown_vat_render_when_present(harness):
    raw = fixture("03")["raw"]
    item = raw["items"][0] | {"discount": 0.5, "vat_rate": None, "reference_price": 1.95}
    item |= {"reference_unit": "l"}
    harness.parser.default = output_of(raw | {"items": [item]})
    await parsed(harness)
    await harness.tap(USER, ITEMS)

    await harness.tap(USER, "Aigua amb gas Pellegrino · 2 pcs · 2.78")

    body = last_text(harness)
    assert "Discount: 0.50" in body
    assert "1.95 per l" in body
    assert "VAT" not in body


async def test_a_deleted_receipts_items_are_not_reachable_from_an_old_button(harness):
    summary_id = await parsed(harness)
    items_data = harness.last_keyboard()[1].inline_keyboard[0][0].callback_data
    await harness.tap(USER, DELETE)
    await harness.tap(USER, "🗑 Yes, delete")

    await harness.press(USER, items_data, summary_id)

    alerts = [c for c in harness.session.calls if isinstance(c, AnswerCallbackQuery) and c.text]
    assert alerts[-1].text == i18n.get("card-deleted-alert")


async def test_opening_the_items_costs_the_same_for_5_and_40_items(harness, statements):
    counts = []
    for count, number in ((5, "A"), (40, "B")):
        harness.parser.default = output_of(many_items(count, number=number))
        await parsed(harness, file_id=f"photo-{number}")
        statements.clear()

        await harness.tap(USER, ITEMS)

        counts.append(len(statements))

    assert counts[0] == counts[1]
    assert counts[0] > 0


def test_every_category_has_a_name():
    for category in Category:
        key = f"category-{category.replace('_', '-')}"
        assert i18n.get(key) != key, key
