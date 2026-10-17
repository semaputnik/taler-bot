"""The item window's edit buttons (ReceiptCard `item`, `item_input`, `item_category`)."""

from decimal import Decimal

import pytest
from aiogram.methods import AnswerCallbackQuery
from sqlalchemy import text

from src.bot.handlers.dialog.receipt_card.common import CATEGORIES
from src.bot.i18n import DEFAULT_LOCALE, create_translator_hub
from src.domain.enums import Category
from src.services.container import Services
from tests.stubs import fixture, output_of

USER = 7
ITEMS = "📋 Items"
BACK = "◀ Back"
NAME = "✏️ Name"
CATEGORY = "🏷 Category"
QUANTITY = "🔢 Quantity"
UNIT_PRICE = "💶 Unit price"
LINE_TOTAL = "🧾 Line total"
FREE_LIMO = "Cervesa Free Limo · 6 pcs · 4.80 €"
PELLEGRINO = "Aigua amo gas Pellegrino · 2 pcs · 2.78 €"

i18n = create_translator_hub().get_translator_by_locale(DEFAULT_LOCALE)
ERROR = i18n.get("issue-input-error", hint="{hint}").split("{hint}")[0]


@pytest.fixture(autouse=True)
async def _allowed(allow_user):
    await allow_user(USER)


async def receipt(harness, *, number: str = "N1", file_id: str = "f1") -> int:
    raw = fixture("03")["raw"]
    harness.parser.default = output_of(
        raw | {"issues": [], "receipt": raw["receipt"] | {"number": number}}
    )
    await harness.send_photo(user_id=USER, file_id=file_id)
    await harness.tasks.drain()
    return harness.last_keyboard()[0]


async def open_item(harness, row: str = FREE_LIMO) -> None:
    await harness.tap(USER, ITEMS)
    await harness.tap(USER, row)


def list_rows(harness) -> list[str]:
    return harness.button_texts()


async def test_the_item_window_offers_the_five_edits_and_back(harness):
    await receipt(harness)

    await open_item(harness)

    assert harness.button_texts() == [NAME, CATEGORY, QUANTITY, UNIT_PRICE, LINE_TOTAL, BACK]
    rows = [[b.text for b in row] for row in harness.last_keyboard()[1].inline_keyboard]
    assert rows == [[NAME, CATEGORY], [QUANTITY, UNIT_PRICE], [LINE_TOTAL], [BACK]]


async def test_renaming_shows_in_the_item_the_list_and_the_next_receipt(harness):
    await receipt(harness)
    await open_item(harness)

    await harness.tap(USER, NAME)
    prompt = harness.last_text()
    assert "Enter the name (free text)" in prompt
    assert "Current value:</b> Cervesa Free Limo" in prompt
    assert harness.button_texts() == [BACK]
    await harness.send_text("Cerveza <Free> Limón", user_id=USER)

    assert harness.last_text().startswith("<b>Cerveza &lt;Free&gt; Limón</b>")
    assert harness.button_texts()[0] == NAME
    await harness.tap(USER, BACK)
    assert "Cerveza <Free> Limón · 6 pcs · 4.80 €" in harness.button_texts()[1]

    await receipt(harness, number="N2", file_id="f2")
    await open_item(harness, "Cerveza <Free> Limón · 6 pcs · 4.80 €")
    assert harness.last_text().startswith("<b>Cerveza &lt;Free&gt; Limón</b>")


async def test_the_category_list_marks_the_current_one_and_a_pick_applies_everywhere(harness):
    await receipt(harness, number="N1", file_id="f1")
    await receipt(harness, number="N2", file_id="f2")
    await open_item(harness)

    await harness.tap(USER, CATEGORY)

    texts = harness.button_texts()
    assert len(texts) == 16
    assert "✓ Drinks" in texts
    assert texts[-1] == BACK
    rows = [len(row) for row in harness.last_keyboard()[1].inline_keyboard]
    assert rows == [2] * 7 + [1, 1]
    await harness.tap(USER, "Snacks")
    assert "<b>Category:</b> Snacks" in harness.last_text()
    await harness.tap(USER, CATEGORY)
    assert "✓ Snacks" in harness.button_texts()
    assert "✓ Drinks" not in harness.button_texts()

    await harness.tap(USER, BACK)
    await harness.tap(USER, BACK)
    await harness.tap(USER, BACK)  # the card of the second receipt is the latest message
    await open_item(harness)
    assert "<b>Category:</b> Snacks" in harness.last_text()


async def test_a_good_number_shows_in_the_item_window(harness):
    await receipt(harness)
    await open_item(harness)

    await harness.tap(USER, QUANTITY)
    assert "Enter the quantity (a number with a point, like 1.5)" in harness.last_text()
    assert "Current value:</b> 6" in harness.last_text()
    await harness.send_text("0,6", user_id=USER)
    assert "<b>Quantity:</b> 0.6 pcs" in harness.last_text()

    await harness.tap(USER, UNIT_PRICE)
    await harness.send_text("8", user_id=USER)
    assert "<b>Unit price:</b> 8.00 €" in harness.last_text()

    await harness.tap(USER, LINE_TOTAL)
    assert "Enter the line total (a number with a point, like 12.50)" in harness.last_text()
    await harness.send_text("4.90", user_id=USER)
    assert "<b>Line total:</b> 4.90 €" in harness.last_text()
    await harness.tap(USER, BACK)
    assert "Cervesa Free Limo · 0.6 pcs · 4.90 €" in harness.button_texts()


@pytest.mark.parametrize(
    ("button", "value"),
    [
        (QUANTITY, "many"),
        (QUANTITY, "0"),
        (QUANTITY, "-2"),
        (UNIT_PRICE, "-1"),
        (LINE_TOTAL, "-0.5"),
        (LINE_TOTAL, "free"),
        (NAME, "   "),
    ],
)
async def test_a_bad_value_shows_the_error_and_changes_nothing(harness, button, value):
    await receipt(harness)
    await open_item(harness)
    await harness.tap(USER, button)

    await harness.send_text(value, user_id=USER)

    assert ERROR in harness.last_text()
    assert "Enter the" in harness.last_text()
    assert harness.button_texts() == [BACK]
    await harness.tap(USER, BACK)
    assert "<b>Cervesa Free Limo</b>" in harness.last_text()
    assert "<b>Quantity:</b> 6 pcs" in harness.last_text()
    assert "<b>Line total:</b> 4.80 €" in harness.last_text()
    assert "<b>Unit price:</b> 0.80 €" in harness.last_text()


async def test_a_bad_value_then_a_good_one_clears_the_error(harness):
    await receipt(harness)
    await open_item(harness)
    await harness.tap(USER, QUANTITY)
    await harness.send_text("0", user_id=USER)

    await harness.send_text("2", user_id=USER)

    assert "<b>Quantity:</b> 2 pcs" in harness.last_text()
    await harness.tap(USER, NAME)
    assert ERROR not in harness.last_text()


async def test_back_from_the_input_and_from_the_categories_changes_nothing(harness):
    await receipt(harness)
    await open_item(harness)
    before = harness.last_text()

    await harness.tap(USER, NAME)
    await harness.tap(USER, BACK)
    assert harness.last_text() == before

    await harness.tap(USER, CATEGORY)
    await harness.tap(USER, BACK)
    assert harness.last_text() == before
    assert harness.button_texts()[0] == NAME


async def test_typed_quantity_and_renamed_product_survive_a_reparse(
    harness, session_factory, make_uow, tmp_storage
):
    await receipt(harness)
    await open_item(harness)
    await harness.tap(USER, QUANTITY)
    await harness.send_text("1.2", user_id=USER)
    await harness.tap(USER, NAME)
    await harness.send_text("Cerveza Free Limón", user_id=USER)
    async with session_factory() as session:
        await session.execute(text("update receipts set status = 'failed'"))
        await session.commit()

    services = Services.build(make_uow, storage=tmp_storage, parser=harness.parser)
    receipt_id = int(
        (await _scalar(session_factory, "select id from receipts")),
    )
    await services.receipts.parse(USER, receipt_id)

    rows = await services.receipts.items(USER, receipt_id)
    row = next(r for r in rows if r.printed_name == "CERV FREE LIMO.")
    assert (row.readable_name, row.quantity) == ("Cerveza Free Limón", Decimal("1.2"))


async def _scalar(session_factory, sql: str):
    async with session_factory() as session:
        return (await session.execute(text(sql))).scalar_one()


async def test_edits_on_a_deleted_receipt_alert_and_return_to_the_card(harness, session_factory):
    await receipt(harness)
    await open_item(harness)
    await harness.tap(USER, NAME)
    async with session_factory() as session:
        await session.execute(text("update receipts set deleted_at = now()"))
        await session.commit()

    await harness.send_text("New name", user_id=USER)

    assert harness.last_text() == i18n.get("card-deleted")
    assert i18n.get("card-deleted-alert") in [m.text for m in harness.sent_messages]
    assert await _scalar(session_factory, "select min(name) from store_products") != "New name"


async def test_a_quantity_on_a_deleted_receipt_alerts(harness, session_factory):
    await receipt(harness)
    await open_item(harness)
    await harness.tap(USER, QUANTITY)
    async with session_factory() as session:
        await session.execute(text("update receipts set deleted_at = now()"))
        await session.commit()

    await harness.send_text("2", user_id=USER)

    assert i18n.get("card-deleted-alert") in [m.text for m in harness.sent_messages]
    assert harness.last_text() == i18n.get("card-deleted")


async def test_a_category_pick_on_a_deleted_receipt_alerts(harness, session_factory):
    await receipt(harness)
    await open_item(harness)
    await harness.tap(USER, CATEGORY)
    async with session_factory() as session:
        await session.execute(text("update receipts set deleted_at = now()"))
        await session.commit()

    await harness.tap(USER, "Snacks")

    alerts = [c for c in harness.session.calls if isinstance(c, AnswerCallbackQuery) and c.text]
    assert (alerts[-1].text, alerts[-1].show_alert) == (i18n.get("card-deleted-alert"), True)
    assert harness.last_text() == i18n.get("card-deleted")
    assert (
        await _scalar(
            session_factory, "select count(*) from store_products where category = 'snacks'"
        )
        == 0
    )


async def test_a_stranger_cannot_edit(harness, session_factory):
    await receipt(harness)
    await open_item(harness)
    await harness.tap(USER, NAME)
    calls = len(harness.session.calls)

    await harness.send_text("Hacked", user_id=999)

    assert len(harness.session.calls) == calls
    assert (
        await _scalar(session_factory, "select count(*) from store_products where name = 'Hacked'")
        == 0
    )


def test_the_bots_category_list_is_the_domains():
    assert set(CATEGORIES) == {str(c) for c in Category}
    assert len(CATEGORIES) == len(set(CATEGORIES))
