"""The /receipts screen through the real dispatcher on real Postgres."""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from itertools import count
from zoneinfo import ZoneInfo

import pytest
from aiogram.methods import EditMessageReplyMarkup, EditMessageText

from src.bot.i18n import DEFAULT_LOCALE, create_translator_hub
from src.domain.receipt import Receipt
from tests.domain.builders import parse, photo, product
from tests.helpers import MakeUow, add_receipt, seed_catalog

USER = 7
RECEIPTS = "🧾 Receipts"
STORES = "Store ▾"
ALL_STORES = "All stores"
PREV_PAGE = "◀"
NEXT_PAGE = "▶"

i18n = create_translator_hub().get_translator_by_locale(DEFAULT_LOCALE)
_ids = count(1)


def this_month() -> tuple[int, int]:
    now = datetime.now(ZoneInfo("Europe/Madrid"))
    return now.year, now.month


def shifted(months: int) -> tuple[int, int]:
    year, month = this_month()
    index = year * 12 + month - 1 + months
    return index // 12, index % 12 + 1


def title(months: int = 0, store: str | None = None) -> str:
    year, month = shifted(months)
    text = f"🗓 {i18n.get(f'month-{month}')} {year}"
    return f"{text} · {store}" if store else text


def label(months: int, arrow: str) -> str:
    name = i18n.get(f"month-short-{shifted(months)[1]}")
    return f"◀ {name}" if arrow == "prev" else f"{name} ▶"


@pytest.fixture(autouse=True)
async def _allowed(allow_user):
    await allow_user(USER)


async def bought(
    make_uow: MakeUow,
    day: int,
    *,
    months: int = 0,
    store: str = "Mercadona",
    total: str = "47.85",
    currency: str = "EUR",
) -> Receipt:
    year, month = shifted(months)
    n = next(_ids)
    key = store.lower()
    one = parse(
        product(f"{key}::item{n}", total=total),
        store_key=key,
        store_name=store,
        purchased_at=datetime(year, month, day, 12, tzinfo=UTC),
        receipt_number=str(n),
        receipt_key=f"{key}|{n}",
        total=Decimal(total),
        currency=currency,
    )
    await seed_catalog(make_uow, one, user_id=USER)
    receipt = Receipt.start(USER, photo(f"hist{n}"))
    receipt.apply_parse(one)
    return await add_receipt(make_uow, receipt, user_id=USER)


async def failed(make_uow: MakeUow, day: int) -> Receipt:
    year, month = this_month()
    n = next(_ids)
    receipt = Receipt.start(
        USER, replace(photo(f"hist{n}"), received_at=datetime(year, month, day, 12, tzinfo=UTC))
    )
    receipt.mark_parsing()
    receipt.mark_failed("The model timed out")
    return await add_receipt(make_uow, receipt, user_id=USER)


def edits(harness) -> list[EditMessageText]:
    return [c for c in harness.session.calls if isinstance(c, EditMessageText)]


async def test_receipts_shows_the_current_month_with_rows_count_and_total(harness, make_uow):
    await bought(make_uow, 14, store="Mercadona", total="47.85")
    await bought(make_uow, 12, store="Lidl", total="23.10")

    await harness.send_text("/receipts", user_id=USER)

    assert harness.last_text() == f"{title()}\n2 receipts · 70.95 €"
    month = f"{this_month()[1]:02d}"
    assert harness.button_texts()[:2] == [
        f"• 14.{month} Mercadona · 47.85 €",
        f"• 12.{month} Lidl · 23.10 €",
    ]


async def test_a_failed_receipt_row_shows_the_cross_and_no_amount(harness, make_uow):
    await bought(make_uow, 14)
    await failed(make_uow, 11)

    await harness.send_text("/receipts", user_id=USER)

    month = f"{this_month()[1]:02d}"
    assert f"• 11.{month} Unknown store · ❌" in harness.button_texts()
    assert harness.last_text().endswith("1 receipt · 47.85 €")


async def test_the_total_is_given_per_currency(harness, make_uow):
    await bought(make_uow, 14, total="10.00")
    await bought(make_uow, 13, total="5.00", currency="USD")

    await harness.send_text("/receipts", user_id=USER)

    text = harness.last_text()
    assert "2 receipts" in text and "10.00 €" in text and "5.00 $" in text


async def test_prev_edits_the_message_to_the_previous_month_and_stops_at_the_oldest(
    harness, make_uow
):
    await bought(make_uow, 14)
    await bought(make_uow, 20, months=-1)
    await harness.send_text("/receipts", user_id=USER)
    message_id = harness.last_keyboard()[0]
    assert label(-1, "prev") in harness.button_texts()

    await harness.tap(USER, label(-1, "prev"))

    assert harness.last_keyboard()[0] == message_id
    assert len(edits(harness)) == 1
    assert harness.last_text().startswith(title(-1))
    assert label(-1, "prev") not in harness.button_texts()
    assert [b for b in harness.button_texts() if b.startswith("◀")] == []
    assert label(0, "next") in harness.button_texts()


async def test_next_is_absent_in_the_current_month_and_present_in_a_past_one(harness, make_uow):
    await bought(make_uow, 14)
    await bought(make_uow, 20, months=-1)
    await harness.send_text("/receipts", user_id=USER)
    assert not [b for b in harness.button_texts() if b.endswith("▶")]

    await harness.tap(USER, label(-1, "prev"))
    assert [b for b in harness.button_texts() if b.endswith("▶")]

    await harness.tap(USER, label(0, "next"))
    assert harness.last_text().startswith(title(0))


async def test_the_store_chooser_filters_rows_and_totals_and_the_filter_survives_prev(
    harness, make_uow
):
    await bought(make_uow, 14, store="Mercadona", total="40.00")
    await bought(make_uow, 12, store="Lidl", total="20.00")
    await bought(make_uow, 9, months=-1, store="Lidl", total="5.00")
    await bought(make_uow, 8, months=-1, store="Mercadona", total="6.00")
    await harness.send_text("/receipts", user_id=USER)

    await harness.tap(USER, STORES)
    assert harness.button_texts() == ["Lidl", "Mercadona", ALL_STORES, "◀ Back"]
    assert harness.last_text().startswith(title())

    await harness.tap(USER, "Lidl")
    assert harness.last_text() == f"{title(0, 'Lidl')}\n1 receipt · 20.00 €"
    assert len([b for b in harness.button_texts() if b.startswith("•")]) == 1

    await harness.tap(USER, STORES)
    assert "✓ Lidl" in harness.button_texts()
    await harness.tap(USER, "◀ Back")
    assert harness.last_text().startswith(title(0, "Lidl"))

    await harness.tap(USER, label(-1, "prev"))
    assert harness.last_text() == f"{title(-1, 'Lidl')}\n1 receipt · 5.00 €"

    await harness.tap(USER, STORES)
    await harness.tap(USER, ALL_STORES)
    assert harness.last_text() == f"{title(-1)}\n2 receipts · 11.00 €"


async def test_a_store_name_is_escaped_in_the_header(harness, make_uow):
    await bought(make_uow, 14, store="<b>Shop")
    await harness.send_text("/receipts", user_id=USER)
    await harness.tap(USER, STORES)

    await harness.tap(USER, "<b>Shop")

    assert harness.last_text().startswith(title(0, "&lt;b&gt;Shop"))


async def test_paging_appears_at_nine_receipts(harness, make_uow):
    for day in range(1, 9):
        await bought(make_uow, day)
    await harness.send_text("/receipts", user_id=USER)
    assert not [b for b in harness.button_texts() if "/" in b]

    await bought(make_uow, 9)
    await harness.send_text("/receipts", user_id=USER)
    rows = [b for b in harness.button_texts() if b.startswith("•")]
    assert len(rows) == 8
    assert "1/2" in harness.button_texts()
    assert PREV_PAGE not in harness.button_texts()

    await harness.tap(USER, NEXT_PAGE)

    rows = [b for b in harness.button_texts() if b.startswith("•")]
    assert rows == [f"• 01.{this_month()[1]:02d} Mercadona · 47.85 €"]
    assert "2/2" in harness.button_texts()
    assert NEXT_PAGE not in harness.button_texts()
    await harness.tap(USER, PREV_PAGE)
    assert "1/2" in harness.button_texts()


async def test_an_empty_month_says_so_and_still_offers_the_arrow(harness, make_uow):
    await bought(make_uow, 14, months=-2)

    await harness.send_text("/receipts", user_id=USER)

    assert harness.last_text() == f"{title()}\n{i18n.get('history-empty')}"
    assert label(-1, "prev") in harness.button_texts()
    assert not [b for b in harness.button_texts() if b.startswith("•")]


async def test_a_month_with_only_a_failed_receipt_has_no_total(harness, make_uow):
    await failed(make_uow, 11)

    await harness.send_text("/receipts", user_id=USER)

    assert harness.last_text() == f"{title()}\n{i18n.get('history-summary-none')}"


async def test_a_row_tap_sends_a_fresh_card_and_the_history_keeps_its_buttons(harness, make_uow):
    receipt = await bought(make_uow, 14, store="Mercadona")
    await harness.send_text("/receipts", user_id=USER)
    history_id, history_markup = harness.last_keyboard()
    row = harness.button_texts()[0]

    await harness.tap(USER, row)

    card = harness.sent_messages[-1]
    assert "Mercadona" in card.text
    assert harness.session.sent_ids[-1] != history_id
    assert not [m for mid, m in harness.keyboards() if mid == history_id and m != history_markup]
    assert not [c for c in harness.session.calls if isinstance(c, EditMessageReplyMarkup)]
    assert receipt.id is not None

    # The history still works after the card was opened.
    await harness.press(USER, history_markup.inline_keyboard[-1][0].callback_data, history_id)
    assert harness.last_keyboard()[0] == history_id


async def test_start_carries_the_receipts_button_and_it_opens_the_list(harness, make_uow):
    await bought(make_uow, 14)
    await harness.send_text("/start", user_id=USER)
    assert harness.button_texts() == [RECEIPTS]

    await harness.tap(USER, RECEIPTS)

    assert harness.sent_messages[-1].text.startswith(title())
    assert harness.sent_messages[-1].text.endswith("1 receipt · 47.85 €")


async def test_a_strangers_receipts_gets_no_reply(harness):
    await harness.send_text("/receipts", user_id=99)

    assert harness.session.calls == []


async def test_duplicate_and_pending_rows_show_their_icons(harness, make_uow):
    original = await bought(make_uow, 14)
    year, month = this_month()
    n = next(_ids)
    duplicate = Receipt.start(USER, photo(f"hist{n}"))
    again = parse(product("mercadona::dup"), receipt_key="mercadona|dup")
    await seed_catalog(make_uow, again, user_id=USER)
    duplicate.apply_parse(again)
    duplicate.mark_duplicate(original.id)
    await add_receipt(make_uow, duplicate, user_id=USER)
    pending = Receipt.start(USER, replace(photo("pend"), received_at=datetime.now(UTC)))
    await add_receipt(make_uow, pending, user_id=USER)

    await harness.send_text("/receipts", user_id=USER)

    texts = harness.button_texts()
    assert any(t.endswith("· ♻️") for t in texts)
    assert any(t.endswith("· ⏳") for t in texts)
    assert (year, month) == this_month()
