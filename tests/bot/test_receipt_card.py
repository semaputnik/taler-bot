"""The ReceiptCard dialog (delete flow) through the real dispatcher on real Postgres."""

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import AnswerCallbackQuery, EditMessageReplyMarkup, EditMessageText
from aiogram.types import InlineKeyboardMarkup
from sqlalchemy import text

from src.bot.i18n import DEFAULT_LOCALE, create_translator_hub
from src.domain.enums import Category
from src.integration.llm import LLMError
from tests.stubs import fixture, output_of

USER = 7
PHOTO = "🖼 Photo"
DELETE = "🗑 Delete"
CLOSE = "✖ Close"
ITEMS = "📋 Items"
REVIEW = "⚠️ Review (1)"
REVIEW_NO_ITEMS = "⚠️ Review (2)"  # the workflow raises issues for a receipt without lines

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


async def test_the_parse_reply_carries_photo_and_delete_buttons(harness):
    await parsed(harness)

    assert harness.button_texts() == [ITEMS, REVIEW, PHOTO, DELETE, CLOSE]


@pytest.mark.parametrize("outcome", ["not_receipt", "failed"])
async def test_every_parse_outcome_carries_the_keyboard(harness, outcome):
    if outcome == "failed":
        harness.parser.error = LLMError("timed out")
        status = i18n.get("receipt-failed")
    else:
        raw = fixture("03")["raw"] | {"is_receipt": False, "items": [], "issues": []}
        harness.parser.default = output_of(raw)
        status = i18n.get("receipt-not-a-receipt")

    await parsed(harness)

    assert harness.last_text().startswith(status)
    assert "Photo received:" in harness.last_text()
    assert harness.button_texts() == [PHOTO, DELETE, CLOSE]


async def test_the_duplicate_reply_carries_the_keyboard(harness):
    await parsed(harness, file_id="a")
    await parsed(harness, file_id="b")

    body = harness.sent_messages[-1].text
    assert body.startswith("♻️ Already recorded: <b>Consum</b>")
    assert "7.58 €" in body
    assert harness.button_texts() == [PHOTO, DELETE, CLOSE]


async def test_delete_opens_a_confirmation_in_place(harness):
    card_id = await parsed(harness)
    sent_before = len(harness.sent_messages)

    await harness.tap(USER, DELETE)

    assert len(harness.sent_messages) == sent_before
    assert harness.last_text() == i18n.get("card-delete-confirm")
    assert [c for c in harness.session.calls if isinstance(c, EditMessageText)]
    assert harness.button_texts() == ["🗑 Yes, delete", "◀ Back"]
    assert harness.last_keyboard()[0] == card_id


async def test_back_returns_to_the_card(harness):
    await parsed(harness)
    await harness.tap(USER, DELETE)

    await harness.tap(USER, "◀ Back")

    assert "Consum" in harness.last_text()
    assert harness.button_texts() == [ITEMS, REVIEW, PHOTO, DELETE, CLOSE]


async def test_confirming_deletes_the_receipt_and_ends_on_the_deleted_card(
    harness, session_factory, tmp_storage
):
    card_id = await parsed(harness)
    (path,) = stored_files(tmp_storage)
    await harness.tap(USER, DELETE)
    sent_before = len(harness.sent_messages)

    await harness.tap(USER, "🗑 Yes, delete")

    assert await deleted_flags(session_factory) == [True]
    assert stored_files(tmp_storage) == [f".trash/{path}"]
    assert len(harness.sent_messages) == sent_before  # no extra "Deleted" message
    assert harness.last_text() == "🗑 This receipt was deleted."
    assert harness.last_keyboard() == (card_id, InlineKeyboardMarkup(inline_keyboard=[]))


async def test_close_hides_the_current_cards_buttons_and_keeps_its_text(harness):
    card_id = await parsed(harness)
    sent_before = len(harness.sent_messages)

    await harness.tap(USER, CLOSE)

    assert len(harness.sent_messages) == sent_before
    assert harness.last_keyboard() == (card_id, InlineKeyboardMarkup(inline_keyboard=[]))
    assert not [c for c in harness.session.calls if isinstance(c, EditMessageText)]


async def test_close_on_an_older_card_removes_only_its_buttons(harness):
    first = await parsed(harness, file_id="a")
    second = await parsed(harness, file_id="b")
    first_markup = next(m for mid, m in harness.keyboards() if mid == first)
    close_data = first_markup.inline_keyboard[-1][0].callback_data

    await harness.press(USER, close_data, first)

    assert harness.last_keyboard() == (first, InlineKeyboardMarkup(inline_keyboard=[]))
    assert harness.keyboards()[-2][0] == second  # the current card keeps its buttons


async def test_the_card_text_has_the_store_hashtag(harness):
    await parsed(harness)

    text = harness.last_text()
    assert text.startswith("🧾 <b>Consum</b>\n\n")
    assert text.endswith("\n\n#consum")


async def test_a_tap_on_the_current_card_edits_it_in_place(harness):
    card_id = await parsed(harness)
    messages = len(harness.sent_messages)

    await harness.tap(USER, ITEMS)

    assert len(harness.sent_messages) == messages
    edit = next(c for c in reversed(harness.session.calls) if isinstance(c, EditMessageText))
    assert edit.message_id == card_id
    assert edit.text == i18n.get("card-items-title", count="2")
    assert harness.button_texts() == [PELLEGRINO, FREE_LIMO, "◀ Back"]


async def test_a_tap_on_an_older_card_sends_a_fresh_card_and_keeps_the_old_keyboard(harness):
    first_id = await parsed(harness, file_id="a", unique_id="ua")
    first_buttons = harness.last_keyboard()[1]
    raw = fixture("03")["raw"]
    harness.parser.default = output_of(raw | {"receipt": raw["receipt"] | {"number": "OTHER"}})
    second_id = await parsed(harness, file_id="b", unique_id="ub")
    assert second_id != first_id
    sent_before = len(harness.sent_messages)
    first_delete = next(
        b.callback_data for row in first_buttons.inline_keyboard for b in row if b.text == DELETE
    )

    await harness.press(USER, first_delete, first_id)

    assert len(harness.sent_messages) == sent_before + 1
    assert harness.sent_messages[-1].text == i18n.get("card-delete-confirm")
    assert harness.last_keyboard()[0] not in (first_id, second_id)
    # nobody removed the keyboard of the first card
    assert not [
        m for m, markup in harness.keyboards() if m == first_id and not markup.inline_keyboard
    ]


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

    body = harness.last_text()
    assert body.startswith(i18n.get("receipt-failed"))
    assert "Photo received:" in body


async def test_a_duplicate_card_names_the_receipt_it_repeats(harness):
    await parsed(harness, file_id="a")
    await parsed(harness, file_id="b")
    await harness.tap(USER, DELETE)

    await harness.tap(USER, "◀ Back")

    body = harness.last_text()
    assert body.startswith("♻️ Already recorded: <b>Consum</b>")
    assert "7.58 €" in body
    assert "Photo received:" in body


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

PELLEGRINO = "Aigua amb gas Pellegrino · 2 pcs · 2.78 €"
FREE_LIMO = "Cervesa Free Limo · 6 pcs · 4.80 €"


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

    assert harness.button_texts() == [REVIEW_NO_ITEMS, PHOTO, DELETE, CLOSE]


async def test_the_card_of_a_receipt_without_items_has_no_items_button(harness):
    raw = fixture("03")["raw"] | {"items": [], "issues": []}
    harness.parser.default = output_of(raw)
    await parsed(harness)
    await harness.tap(USER, DELETE)

    await harness.tap(USER, "◀ Back")

    assert harness.button_texts() == [REVIEW_NO_ITEMS, PHOTO, DELETE, CLOSE]


async def test_items_opens_the_list_in_place(harness):
    summary_id = await parsed(harness)
    sent_before = len(harness.sent_messages)

    await harness.tap(USER, ITEMS)

    assert len(harness.sent_messages) == sent_before
    assert harness.last_text() == i18n.get("card-items-title", count="2")
    assert harness.last_keyboard()[0] == summary_id
    assert harness.button_texts() == [PELLEGRINO, FREE_LIMO, "◀ Back"]


async def test_a_row_tap_shows_the_item_details(harness):
    await parsed(harness)
    await harness.tap(USER, ITEMS)

    await harness.tap(USER, FREE_LIMO)

    body = harness.last_text()
    assert "<b>Cervesa Free Limo</b>" in body
    assert "CERV FREE LIMO." in body
    assert "Drinks" in body
    assert "6 pcs" in body
    assert "<b>Unit price:</b> 0.80 €" in body
    assert "<b>Line total:</b> 4.80 €" in body
    assert body.startswith("<b>Cervesa Free Limo</b>\n\n")
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
    assert "Consum" in harness.last_text()
    assert harness.button_texts() == [ITEMS, REVIEW, PHOTO, DELETE, CLOSE]


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

    await harness.tap(USER, "Item 10 · 2 pcs · 2.78 €")

    assert "<b>Item 10</b>" in harness.last_text()


async def test_a_discount_and_unknown_vat_render_when_present(harness):
    raw = fixture("03")["raw"]
    item = raw["items"][0] | {"discount": 0.5, "vat_rate": None, "reference_price": 1.95}
    item |= {"reference_unit": "l"}
    harness.parser.default = output_of(raw | {"items": [item]})
    await parsed(harness)
    await harness.tap(USER, ITEMS)

    await harness.tap(USER, "Aigua amb gas Pellegrino · 2 pcs · 2.78 €")

    body = harness.last_text()
    assert "<b>Discount:</b> 0.50 €" in body
    assert "1.95 € per l" in body
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
