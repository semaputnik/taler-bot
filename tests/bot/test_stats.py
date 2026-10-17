"""The /stats screen through the real dispatcher on real Postgres."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from itertools import count
from zoneinfo import ZoneInfo

import pytest
from aiogram.methods import EditMessageText

from src.bot.i18n import DEFAULT_LOCALE, create_translator_hub
from src.bot.keyboards.stats import StatsAction, StatsCallback, StatsKind
from src.domain.enums import Category
from src.domain.receipt import Receipt
from tests.domain.builders import parse, photo, product
from tests.helpers import MakeUow, add_receipt, seed_catalog

USER = 7
RECEIPTS = "🧾 Receipts"
SPENDING = "📊 Spending"
WEEK = "📅 Week"
MONTH = "📅 Month"

i18n = create_translator_hub().get_translator_by_locale(DEFAULT_LOCALE)
_ids = count(1)


def today() -> date:
    return datetime.now(ZoneInfo("Europe/Madrid")).date()


def shifted(months: int) -> tuple[int, int]:
    now = today()
    index = now.year * 12 + now.month - 1 + months
    return index // 12, index % 12 + 1


def month_title(months: int = 0) -> str:
    year, month = shifted(months)
    return f"📊 {i18n.get(f'month-{month}')} {year}"


def month_name(months: int) -> str:
    return i18n.get(f"month-{shifted(months)[1]}")


def short(months: int) -> str:
    return i18n.get(f"month-short-{shifted(months)[1]}")


def monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def week_title(day: date) -> str:
    start = monday(day)
    last = start + timedelta(days=6)
    week = start.isocalendar().week
    return f"📊 Week {week} · {start:%d.%m}–{last:%d.%m.%Y}"


def edits(harness) -> list[EditMessageText]:
    return [c for c in harness.session.calls if isinstance(c, EditMessageText)]


@pytest.fixture(autouse=True)
async def _allowed(allow_user):
    await allow_user(USER)


async def bought(
    make_uow: MakeUow,
    when: date,
    *lines: tuple[Category, str],
    store: str | None = "Mercadona",
    total: str | None = None,
    currency: str = "EUR",
    card: tuple[str, str] | None = None,
) -> Receipt:
    """A parsed receipt of USER bought on `when`; the total is the lines' sum unless given."""
    n = next(_ids)
    key = store.lower() if store else None
    items = tuple(
        product(f"{key or 'nostore'}::item{n}-{i}", total=amount, category=category)
        for i, (category, amount) in enumerate(lines)
    )
    amount = total if total is not None else str(sum((Decimal(a) for _, a in lines), Decimal(0)))
    one = parse(
        *items,
        store_key=key,
        store_name=store,
        purchased_at=datetime(when.year, when.month, when.day, 12, tzinfo=UTC),
        receipt_number=str(n),
        receipt_key=f"{key or 'nostore'}|{n}",
        total=Decimal(amount),
        currency=currency,
        card_brand=card[0] if card else None,
        card_last4=card[1] if card else None,
    )
    if not lines:
        one = replace(one, items=())  # `parse` fills in a default item
    await seed_catalog(make_uow, one, user_id=USER)
    receipt = Receipt.start(USER, photo(f"stat{n}"))
    receipt.apply_parse(one)
    return await add_receipt(make_uow, receipt, user_id=USER)


def in_month(months: int, day: int = 15) -> date:
    year, month = shifted(months)
    return date(year, month, day)


async def seed_two_months(make_uow: MakeUow) -> None:
    visa = ("VISA", "0848")
    await bought(
        make_uow, in_month(0), (Category.PRODUCE, "30.00"), (Category.DAIRY, "10.00"), card=visa
    )
    await bought(make_uow, in_month(0), (Category.PRODUCE, "5.00"), store="Lidl", total="8.00")
    await bought(make_uow, in_month(-1), (Category.PRODUCE, "20.00"), card=visa)


async def test_stats_renders_the_month_with_the_comparison(harness, make_uow):
    await seed_two_months(make_uow)

    await harness.send_text("/stats", user_id=USER)

    assert harness.last_text() == (
        f"{month_title()}\n"
        f"48.00 € · 2 receipts · ▲ 140% vs {month_name(-1)} (20.00 €)\n"
        "\n"
        "<b>Categories</b>\n"
        "▇▇▇▇▇▇▇ Produce 35.00 € · 73% · ▲ 75%\n"
        "▇▇ Dairy 10.00 € · 21% · new\n"
        "▇ Not itemised 3.00 € · 6%\n"
        "\n"
        "<b>Stores</b>\n"
        "Mercadona 40.00 € · 83% · ▲ 100%\n"
        "Lidl 8.00 € · 17% · new\n"
        "\n"
        "<b>Cards</b>\n"
        "VISA •0848 40.00 € · ▲ 100%\n"
        "cash 8.00 € · new"
    )


async def test_a_period_without_a_previous_one_shows_no_comparison(harness, make_uow):
    await bought(make_uow, in_month(0), (Category.MEAT, "10.00"))

    await harness.send_text("/stats", user_id=USER)

    text = harness.last_text()
    assert text.splitlines()[1] == "10.00 € · 1 receipt"
    assert "new" not in text and "▲" not in text
    assert "▇▇▇▇▇▇▇▇▇▇ Meat 10.00 € · 100%" in text.splitlines()


async def test_a_tiny_share_still_gets_one_bar(harness, make_uow):
    await bought(make_uow, in_month(0), (Category.MEAT, "99.00"), (Category.FISH, "0.50"))

    await harness.send_text("/stats", user_id=USER)

    assert "▇ Fish 0.50 € · 1%" in harness.last_text().splitlines()


async def test_prev_edits_to_the_previous_month_and_next_is_only_in_a_past_one(harness, make_uow):
    await seed_two_months(make_uow)
    await harness.send_text("/stats", user_id=USER)
    message_id = harness.last_keyboard()[0]
    assert f"◀ {short(-1)}" in harness.button_texts()
    assert not [b for b in harness.button_texts() if b.endswith("▶")]

    await harness.tap(USER, f"◀ {short(-1)}")

    assert harness.last_keyboard()[0] == message_id
    assert len(edits(harness)) == 1
    assert harness.last_text().startswith(f"{month_title(-1)}\n20.00 € · 1 receipt")
    assert f"{short(0)} ▶" in harness.button_texts()
    assert not [b for b in harness.button_texts() if b.startswith("◀")]

    await harness.tap(USER, f"{short(0)} ▶")
    assert harness.last_text().startswith(month_title(0))


async def test_week_switches_to_the_week_of_the_first_and_prev_moves_one_week(harness, make_uow):
    first = in_month(0, 1)
    await bought(make_uow, first, (Category.PRODUCE, "10.00"))
    await bought(make_uow, first - timedelta(days=7), (Category.DAIRY, "4.00"))
    await bought(make_uow, first - timedelta(days=30), (Category.MEAT, "1.00"))
    await harness.send_text("/stats", user_id=USER)

    await harness.tap(USER, WEEK)

    assert harness.last_text().startswith(f"{week_title(first)}\n10.00 € · 1 receipt")
    assert "▲ 150% vs previous week (4.00 €)" in harness.last_text()
    before = monday(first) - timedelta(days=7)
    assert f"◀ {before:%d.%m}" in harness.button_texts()
    assert RECEIPTS not in harness.button_texts()
    assert MONTH in harness.button_texts()

    await harness.tap(USER, f"◀ {before:%d.%m}")

    assert harness.last_text().startswith(f"{week_title(before)}\n4.00 € · 1 receipt")
    assert f"{monday(first):%d.%m} ▶" in harness.button_texts()

    await harness.tap(USER, MONTH)
    assert harness.last_text().startswith(f"📊 {i18n.get(f'month-{before.month}')} {before.year}")


async def test_the_week_header_uses_iso_week_numbers_across_a_year_boundary(harness, make_uow):
    await bought(make_uow, date(2025, 12, 31), (Category.PRODUCE, "10.00"))
    await harness.send_text("/stats", user_id=USER)
    # Walk back to the old week: the arrows carry the anchor, so press a hand-made callback.
    message_id = harness.last_keyboard()[0]
    data = StatsCallback(
        kind=StatsKind.WEEK, year=2025, month=12, day=31, action=StatsAction.SHOW
    ).pack()
    await harness.press(USER, data, message_id)

    assert harness.last_text().startswith("📊 Week 1 · 29.12–04.01.2026\n10.00 € · 1 receipt")


async def test_an_empty_period_says_so_and_still_offers_the_arrow(harness, make_uow):
    await bought(make_uow, in_month(-2), (Category.PRODUCE, "10.00"))

    await harness.send_text("/stats", user_id=USER)

    assert harness.last_text() == f"{month_title()}\n{i18n.get('stats-empty')}"
    assert harness.last_text().endswith("No purchases in this period.")
    assert f"◀ {short(-1)}" in harness.button_texts()
    assert RECEIPTS in harness.button_texts()


async def test_two_currencies_give_two_headed_blocks(harness, make_uow):
    await bought(make_uow, in_month(0), (Category.PRODUCE, "10.00"))
    await bought(make_uow, in_month(0), (Category.PRODUCE, "5.00"), currency="USD", store="Shop")

    await harness.send_text("/stats", user_id=USER)

    text = harness.last_text()
    assert text.startswith(f"{month_title()}\n<b>EUR</b>\n10.00 € · 1 receipt")
    assert "\n\n<b>USD</b>\n5.00 $ · 1 receipt" in text
    assert text.index("EUR") < text.index("USD")


async def test_receipts_button_sends_the_history_of_the_month_as_a_new_message(harness, make_uow):
    await seed_two_months(make_uow)
    await harness.send_text("/stats", user_id=USER)
    await harness.tap(USER, f"◀ {short(-1)}")
    stats_id = harness.last_keyboard()[0]

    await harness.tap(USER, RECEIPTS)

    year, month = shifted(-1)
    sent = harness.sent_messages[-1]
    assert sent.text.startswith(f"🗓 {i18n.get(f'month-{month}')} {year}")
    assert sent.text.endswith("1 receipt · 20.00 €")
    assert harness.session.sent_ids[-1] != stats_id


async def test_start_carries_the_spending_button_and_it_sends_the_stats_as_a_new_message(
    harness, make_uow
):
    await seed_two_months(make_uow)
    await harness.send_text("/start", user_id=USER)
    assert harness.button_texts() == [RECEIPTS, SPENDING]
    greeting_id = harness.last_keyboard()[0]

    await harness.tap(USER, SPENDING)

    assert harness.sent_messages[-1].text.startswith(f"{month_title()}\n48.00 € · 2 receipts")
    assert harness.session.sent_ids[-1] != greeting_id
    assert not edits(harness)


async def test_store_and_card_names_are_escaped(harness, make_uow):
    await bought(
        make_uow, in_month(0), (Category.PRODUCE, "10.00"), store="<b>Shop", card=("<i>X", "1234")
    )

    await harness.send_text("/stats", user_id=USER)

    text = harness.last_text()
    assert "&lt;b&gt;Shop" in text and "&lt;i&gt;X •1234" in text


async def test_a_receipt_without_a_store_gets_the_unknown_store_label(harness, make_uow):
    await bought(make_uow, in_month(0), store=None, total="10.00")

    await harness.send_text("/stats", user_id=USER)

    assert "Unknown store 10.00 € · 100%" in harness.last_text().splitlines()


async def test_a_strangers_stats_gets_no_reply(harness):
    await harness.send_text("/stats", user_id=99)

    assert harness.session.calls == []
