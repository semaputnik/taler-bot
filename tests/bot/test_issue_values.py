"""Reading a typed value by the kind of input the issue screen asked for."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from src.bot.handlers.dialog.receipt_card.values import InvalidValue, parse_date, parse_value

MADRID = ZoneInfo("Europe/Madrid")


def test_a_datetime_is_read_in_the_users_time_zone():
    value = parse_value("datetime", " 05.10.2026 18:30 ", MADRID)

    assert value.tzinfo is not None
    assert value.astimezone(UTC) == datetime(2026, 10, 5, 16, 30, tzinfo=UTC)


@pytest.mark.parametrize("text", ["2026-10-05 18:30", "05.10.2026", "32.10.2026 10:00", "x", ""])
def test_a_bad_datetime_is_refused(text):
    with pytest.raises(InvalidValue):
        parse_value("datetime", text, MADRID)


@pytest.mark.parametrize("kind", ["money", "number"])
@pytest.mark.parametrize(
    ("text", "expected"),
    [("12.30", "12.30"), ("12,30", "12.30"), (" 7 ", "7"), ("-1,5", "-1.5"), (".5", "0.5")],
)
def test_a_number_takes_a_point_or_a_comma(kind, text, expected):
    assert parse_value(kind, text, MADRID) == Decimal(expected)


@pytest.mark.parametrize(
    "text", ["abc", "", "1.2.3", "NaN", "inf", "1_000", "1 000", "123456789", "1e5", "€5"]
)
def test_a_non_number_is_refused(text):
    with pytest.raises(InvalidValue):
        parse_value("money", text, MADRID)


def test_last4_is_exactly_four_digits():
    assert parse_value("last4", " 1234 ", MADRID) == "1234"
    for text in ["123", "12345", "12a4", ""]:
        with pytest.raises(InvalidValue):
            parse_value("last4", text, MADRID)


def test_a_currency_is_three_letters_upper_cased():
    assert parse_value("currency", "eur", MADRID) == "EUR"
    for text in ["eu", "euro", "e1r", ""]:
        with pytest.raises(InvalidValue):
            parse_value("currency", text, MADRID)


def test_text_is_stripped_and_not_empty():
    assert parse_value("text", "  Visa  ", MADRID) == "Visa"
    with pytest.raises(InvalidValue):
        parse_value("text", "   ", MADRID)


def test_an_unknown_kind_is_refused():
    with pytest.raises(InvalidValue):
        parse_value(None, "x", MADRID)


# --- dates of a manual entry ----------------------------------------------------------------

TODAY = date(2026, 10, 17)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("05.10", date(2026, 10, 5)),
        (" 5.3 ", date(2026, 3, 5)),
        ("17.10", TODAY),
        ("31.12.2025", date(2025, 12, 31)),
        ("17.10.2026", TODAY),
        ("29.02.2024", date(2024, 2, 29)),
    ],
)
def test_a_date_is_day_month_with_or_without_the_year(text, expected):
    assert parse_date(text, TODAY) == expected


@pytest.mark.parametrize(
    "text",
    ["", "x", "18.10", "01.01.2027", "20.12", "32.01", "00.05", "10.13", "29.02", "2026-10-05",
     "5/10", "05.10.26", "05.10.2026.1", "1.2.3"],
)  # fmt: skip
def test_a_future_or_malformed_date_is_refused(text):
    with pytest.raises(InvalidValue):
        parse_date(text, TODAY)


def test_the_date_kind_reads_against_todays_date_in_the_users_zone():
    today = datetime.now(MADRID).date()

    assert parse_value("date", today.strftime("%d.%m.%Y"), MADRID) == today
    with pytest.raises(InvalidValue):
        parse_value("date", (today + timedelta(days=1)).strftime("%d.%m.%Y"), MADRID)
