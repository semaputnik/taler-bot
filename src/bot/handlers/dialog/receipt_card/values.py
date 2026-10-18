"""Turn the text a user typed into the value a service takes.

The input kinds are the services' `IssueCard.input_kind`. The domain validates the value
again; this module only reads the formats the screen asks for.
"""

import re
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

DATETIME_FORMAT = "%d.%m.%Y %H:%M"

_NUMBER = re.compile(r"[+-]?(\d{1,8}([.,]\d+)?|[.,]\d+)", re.ASCII)
_LAST4 = re.compile(r"\d{4}", re.ASCII)
_CURRENCY = re.compile(r"[A-Za-z]{3}", re.ASCII)
_DATE = re.compile(r"(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?", re.ASCII)


class InvalidValue(ValueError):
    """The text does not fit the kind of value the screen asked for."""


def parse_date(text: str, today: date) -> date:
    """`dd.mm` (this year of `today`) or `dd.mm.yyyy`; a day after `today` is refused."""
    found = _DATE.fullmatch(text.strip())
    if found is None:
        raise InvalidValue(text)
    day, month, year = found.groups()
    try:
        value = date(int(year) if year else today.year, int(month), int(day))
    except ValueError as exc:
        raise InvalidValue(text) from exc
    if value > today:
        raise InvalidValue(text)
    return value


def parse_value(kind: str | None, text: str, tz: ZoneInfo) -> Decimal | datetime | date | str:
    text = text.strip()
    match kind:
        case "datetime":
            try:
                return datetime.strptime(text, DATETIME_FORMAT).replace(tzinfo=tz)
            except ValueError as exc:
                raise InvalidValue(text) from exc
        case "date":
            return parse_date(text, datetime.now(tz).date())
        case "money" | "number":
            if not _NUMBER.fullmatch(text):
                raise InvalidValue(text)
            return Decimal(text.replace(",", "."))
        case "last4":
            if not _LAST4.fullmatch(text):
                raise InvalidValue(text)
            return text
        case "currency":
            if not _CURRENCY.fullmatch(text):
                raise InvalidValue(text)
            return text.upper()
        case "text":
            if not text:
                raise InvalidValue(text)
            return text
    raise InvalidValue(text)


# The editable fields of an item and the input kind each is read as.
ITEM_FIELD_KINDS = {
    "name": "text",
    "quantity": "number",
    "unit_price": "number",
    "line_total": "money",
}
