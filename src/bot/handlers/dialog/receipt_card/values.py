"""Turn the text a user typed for an issue into the value `correct_issue` takes.

The input kinds are the services' `IssueCard.input_kind`. The domain validates the value
again; this module only reads the formats the screen asks for.
"""

import re
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

DATETIME_FORMAT = "%d.%m.%Y %H:%M"

_NUMBER = re.compile(r"[+-]?(\d{1,8}([.,]\d+)?|[.,]\d+)")
_LAST4 = re.compile(r"\d{4}")
_CURRENCY = re.compile(r"[A-Za-z]{3}")


class InvalidValue(ValueError):
    """The text does not fit the kind of value the screen asked for."""


def parse_value(kind: str | None, text: str, tz: ZoneInfo) -> Decimal | datetime | str:
    text = text.strip()
    match kind:
        case "datetime":
            try:
                return datetime.strptime(text, DATETIME_FORMAT).replace(tzinfo=tz)
            except ValueError as exc:
                raise InvalidValue(text) from exc
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
