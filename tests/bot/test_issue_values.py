"""Reading a typed value by the kind of input the issue screen asked for."""

from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from src.bot.handlers.dialog.receipt_card.values import InvalidValue, parse_value

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
