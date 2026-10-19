"""`normalize`: the pure port of n8n's "Normalize Receipt".

The JavaScript is `docs/n8n-reference/normalize_receipt.js`.

Rules run in the same order as the JavaScript, so the two can be read side by side.
"""

import re
from collections.abc import Collection, Mapping
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo

from src.domain.enums import IssueSeverity, IssueSource, ProductCategory
from src.domain.parse import Parse, ParsedIssue, ParsedItem
from src.domain.slug import slug, strip
from src.exception import InvalidReceiptData

# Bump whenever the prompt, the schema, the model or this module changes (n8n was 2026-10-15.1).
PARSER_VERSION = "2026-10-19.1"  # product category `produce` renamed `fruit_and_vegetables`

TOLERANCE = Decimal("0.02")

UNITS = {
    "pcs": "pcs",
    "pc": "pcs",
    "ud": "pcs",
    "uds": "pcs",
    "u": "pcs",
    "un": "pcs",
    "unit": "pcs",
    "units": "pcs",
    "шт": "pcs",
    "kg": "kg",
    "кг": "kg",
    "g": "g",
    "gr": "g",
    "г": "g",
    "l": "l",
    "lt": "l",
    "л": "l",
    "ml": "ml",
    "мл": "ml",
}
LEGAL_SUFFIX = re.compile(
    r"(^|\s)(s\.?\s?a\.?\s?u?\.?|s\.?\s?l\.?\s?u?\.?|ltd\.?|llc|gmbh|inc\.?|ооо|ип)(?=\s|$)",
    re.IGNORECASE,
)
LEADING_QUANTITY = re.compile(r"(\d+(?:[.,]\d+)?)\s*[x×*]?\s+(.+)", re.IGNORECASE)
NAME_NOTES = frozenset({"unknown_abbreviation", "ambiguous"})
LENIENT_DATETIME = re.compile(
    r"\s*(\d{4})-(\d{1,2})-(\d{1,2})[ T](\d{1,2}):(\d{2})(?::(\d{2}))?\s*"
)


def clean(s: Any) -> str | None:
    if s is None:
        return None
    return str(s).strip() or None


def round_to(n: Decimal, places: str) -> Decimal:
    return n.quantize(Decimal(places), rounding=ROUND_HALF_UP)


def num(v: Any) -> Decimal | None:
    """A number rounded to 4 decimals, or None for anything that is not one."""
    if v is None or v == "" or isinstance(v, bool):
        return None
    try:
        if isinstance(v, Decimal):
            n = v
        elif isinstance(v, int | float):
            n = Decimal(str(v))
        else:
            n = Decimal(re.sub(r"\s", "", str(v)).replace(",", ".", 1))
    except InvalidOperation:
        return None
    if not n.is_finite():
        return None
    return round_to(n, "0.0001")


def round2(n: Decimal) -> Decimal:
    return round_to(n, "0.01")


def fmt(n: Decimal | None) -> str:
    """A number the way JavaScript prints it: 50.4, 10, never 50.4000; `na` for none."""
    return "na" if n is None else format(n.normalize(), "f")


def unit_of(u: Any) -> str:
    key = re.sub(r"[^a-zа-я]", "", strip(u).lower())
    if key in UNITS:
        return UNITS[key]
    return strip(u).lower() if clean(u) else "pcs"


def parse_printed(printed: str, zone: ZoneInfo) -> datetime | None:
    """ISO first, then a lenient `YYYY-MM-DD HH:MM[:SS]`; naive values are read in `zone`."""
    try:
        parsed = datetime.fromisoformat(printed)
    except ValueError:
        m = LENIENT_DATETIME.fullmatch(printed)
        if not m:
            return None
        year, month, day, hour, minute, second = (int(g or 0) for g in m.groups())
        try:
            parsed = datetime(year, month, day, hour, minute, second)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=zone)
    return parsed.astimezone(zone)


def with_year(moment: datetime, year: int) -> datetime:
    try:
        return moment.replace(year=year)
    except ValueError:  # 29 February in a year without one
        return moment.replace(year=year, day=28)


def jsonable(value: Any) -> Any:
    """The raw model output as JSON-safe plain data (Decimal becomes int or float)."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Mapping):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [jsonable(v) for v in value]
    return value


# Category names the model or n8n used before a rename; old raw readings still carry them.
LEGACY_CATEGORIES = {"produce": ProductCategory.FRUIT_AND_VEGETABLES}


def category_of(value: Any) -> ProductCategory:
    name = str(value).lower()
    if name in LEGACY_CATEGORIES:
        return LEGACY_CATEGORIES[name]
    try:
        return ProductCategory(name)
    except ValueError:
        return ProductCategory.OTHER


def severity_of(value: Any) -> IssueSeverity:
    try:
        return IssueSeverity(str(value).lower())
    except ValueError:
        return IssueSeverity.MEDIUM


def normalize(
    raw: Mapping[str, Any],
    *,
    received_at: datetime,
    timezone: str,
    known_product_keys: Collection[str],
    known_card_last4: Collection[str],
    parser_version: str,
    model: str | None,
) -> Parse:
    """Turn the model's reading of a receipt into a `Parse`.

    `raw` is plain data in the shape of `docs/n8n-reference/receipt_schema.json`:
    `integration/llm` validates the model output with `RawParse` and passes `model_dump()`.
    `received_at` is the Telegram message time (aware); `known_product_keys` are the user's
    existing catalog keys and `known_card_last4` the card endings of their earlier parsed
    receipts. Money and quantities are `Decimal`; `purchased_at` is aware, in `timezone`.

    Raises `InvalidReceiptData` when the reading cannot be normalized (a number out of range,
    a malformed structure), so a caller has one error to expect.
    """
    try:
        return _normalize(
            raw,
            received_at=received_at,
            timezone=timezone,
            known_product_keys=known_product_keys,
            known_card_last4=known_card_last4,
            parser_version=parser_version,
            model=model,
        )
    except (ArithmeticError, LookupError, TypeError, ValueError, AttributeError) as error:
        raise InvalidReceiptData(f"cannot normalize the reading: {type(error).__name__}") from error


def _normalize(
    raw: Mapping[str, Any],
    *,
    received_at: datetime,
    timezone: str,
    known_product_keys: Collection[str],
    known_card_last4: Collection[str],
    parser_version: str,
    model: str | None,
) -> Parse:
    ai = raw
    raw_output = jsonable(dict(raw))
    if ai.get("is_receipt") is False:
        return Parse(
            is_receipt=False, raw_output=raw_output, model=model, parser_version=parser_version
        )

    issues: list[ParsedIssue] = []

    def flag(
        issue_type: str,
        severity: IssueSeverity,
        field: str,
        message: str,
        item_name: str | None = None,
    ) -> None:
        issues.append(
            ParsedIssue(
                source=IssueSource.WORKFLOW,
                issue_type=issue_type,
                severity=severity,
                field=field,
                item_name=item_name,
                message=message,
            )
        )

    store = ai.get("store") or {}
    store_name = clean(store.get("name")) or clean(store.get("legal_name")) or "Unknown store"
    store_key = slug(LEGAL_SUFFIX.sub(" ", store_name)) or "unknown-store"

    zone = ZoneInfo(timezone)
    if received_at.tzinfo is None:
        raise InvalidReceiptData("received_at must be timezone-aware")
    received = received_at.astimezone(zone)
    receipt = ai.get("receipt") or {}
    printed = clean(receipt.get("purchased_at"))
    purchased = parse_printed(printed, zone) if printed else None
    if not printed:
        flag(
            "missing_field",
            IssueSeverity.MEDIUM,
            "receipt.purchased_at",
            "No purchase time on the receipt; used the Telegram message time.",
        )
    elif purchased is None:
        flag(
            "ambiguous",
            IssueSeverity.HIGH,
            "receipt.purchased_at",
            f'Unparseable purchase time "{printed}"; used the Telegram message time.',
        )
    if purchased is None:
        purchased = received
    # A receipt is photographed shortly after the purchase. A date far from the message date is
    # almost always a misread year, which would also shift the duplicate key and the price history,
    # so try the message's year first.
    earliest = received - timedelta(days=60)
    latest = received + timedelta(days=1)
    if purchased < earliest or purchased > latest:
        read: date = purchased.date()
        fixed = next(
            (
                d
                for d in (
                    with_year(purchased, received.year),
                    with_year(purchased, received.year - 1),
                )
                if earliest <= d <= latest
            ),
            None,
        )
        if fixed:
            purchased = fixed
            flag(
                "corrected",
                IssueSeverity.MEDIUM,
                "receipt.purchased_at",
                f"Read the date as {read}, but the photo was sent on {received.date()}; "
                f"assumed a misread year and used {fixed.date()}.",
            )
        else:
            flag(
                "ambiguous",
                IssueSeverity.HIGH,
                "receipt.purchased_at",
                f"Purchase date {read} is far from the date the photo was sent "
                f"({received.date()}); kept as read, check the receipt.",
            )

    currency = (clean(ai.get("currency")) or "EUR").upper()
    totals = ai.get("totals") or {}
    payment = ai.get("payment") or {}
    total = num(totals.get("total"))
    if total is None:
        total = num(payment.get("amount_paid"))
    # Duplicate key. Store name, receipt number and money read the same across runs; the printed
    # minute and the tax id (often blurry, sometimes null) do not. The date stays in the key because
    # some stores restart receipt numbering every day.
    receipt_no = re.sub(r"\s+", "", clean(receipt.get("number")) or "").upper()
    if receipt_no:
        receipt_key = "|".join([store_key, receipt_no, f"{purchased:%Y-%m-%d}", fmt(total)])
    else:
        receipt_key = "|".join([store_key, f"{purchased:%Y-%m-%dT%H:%M}", fmt(total)])

    key_by_raw: dict[str, str] = {}
    items: list[ParsedItem] = []
    for it in ai.get("items") or []:
        if not (clean(it.get("name_normalized")) or clean(it.get("name_raw"))):
            continue
        quantity = num(it.get("quantity"))
        if quantity is None:
            quantity = Decimal(1)
        # Drop a leading "2 " / "2x " that repeats the quantity, so the product key does not change
        # with the amount bought.
        name_raw = clean(it.get("name_raw"))
        lead = LEADING_QUANTITY.fullmatch(name_raw or "")
        if lead and num(lead.group(1)) == quantity:
            name_raw = lead.group(2).strip()
        product_name = clean(it.get("name_normalized")) or name_raw
        line_total = num(it.get("line_total"))
        unit = unit_of(it.get("unit"))
        reference_price = num(it.get("reference_price"))
        reference_unit = (
            unit_of(it.get("reference_unit")) if clean(it.get("reference_unit")) else None
        )
        unit_price = num(it.get("unit_price"))
        if unit_price is None and reference_unit == unit:
            unit_price = reference_price
        if unit_price is None and line_total is not None and quantity:
            unit_price = round_to(line_total / quantity, "0.0001")
        # The printed line text comes from the store's POS and is stable across receipts; the LLM's
        # normalized name is not.
        product_key = f"{store_key}::{slug(name_raw) or slug(product_name)}"
        printed_raw = clean(it.get("name_raw"))
        if printed_raw:
            key_by_raw[printed_raw] = product_key
        discount = num(it.get("discount"))
        items.append(
            ParsedItem(
                product_key=product_key,
                printed_name=name_raw or product_name or "",
                readable_name=product_name or "",
                category=category_of(clean(it.get("category")) or "other"),
                quantity=quantity,
                unit=unit,
                unit_price=unit_price,
                reference_price=reference_price,
                reference_unit=reference_unit,
                discount=Decimal(0) if discount is None else discount,
                line_total=line_total,
                vat_rate=num(it.get("vat_rate")),
            )
        )

    card_raw = clean(payment.get("card_last4"))
    last4 = re.sub(r"\D", "", card_raw or "")[-4:] or None

    # Name notes on a product already in the catalog repeat on every receipt that has it, and its
    # name there has already been settled (or corrected by hand), so they are dropped.
    known_keys = set(known_product_keys)
    for i in ai.get("issues") or []:
        item_name = clean(i.get("item_name_raw"))
        key = (
            (key_by_raw.get(item_name) or f"{store_key}::{slug(item_name)}") if item_name else None
        )
        issue_type = str(jsonable(i.get("type")) or "other")
        if (
            key
            and issue_type in NAME_NOTES
            and (clean(i.get("field")) or "").startswith("items.name")
            and key in known_keys
        ):
            continue
        issues.append(
            ParsedIssue(
                source=IssueSource.MODEL,
                issue_type=issue_type,
                severity=severity_of(jsonable(i.get("severity")) or "medium"),
                field=clean(i.get("field")),
                item_name=item_name,
                message=clean(i.get("message")) or "",
            )
        )

    if store_key == "unknown-store":
        flag(
            "missing_field",
            IssueSeverity.HIGH,
            "store.name",
            "Store name not recognised; products are keyed under unknown-store.",
        )
    if total is None:
        flag("missing_field", IssueSeverity.HIGH, "totals.total", "No total on the receipt.")
    if not clean(ai.get("currency")):
        flag(
            "missing_field",
            IssueSeverity.LOW,
            "currency",
            "No currency on the receipt; assumed EUR.",
        )
    if card_raw and not re.fullmatch(r"\d{4}", last4 or ""):
        # Only the tail: the card number is never kept, not even in a message.
        flag(
            "ambiguous",
            IssueSeverity.LOW,
            "payment.card_last4",
            f'Card digits "{card_raw[-4:]}" are not 4 digits.',
        )
    # The household pays with a handful of cards, so an unseen ending is more often a misread digit
    # than a new card.
    known_cards = sorted({c for c in (clean(c) for c in known_card_last4) if c})
    if last4 and re.fullmatch(r"\d{4}", last4) and known_cards and last4 not in known_cards:
        flag(
            "ambiguous",
            IssueSeverity.MEDIUM,
            "payment.card_last4",
            f"Card ending {last4} has not been seen before (known: {', '.join(known_cards)}); "
            "check for a misread digit, ignore if it is a new card.",
        )
    if not items:
        flag("missing_field", IssueSeverity.HIGH, "items", "No product lines extracted.")
    for item in items:
        if item.line_total is None:
            flag(
                "missing_field",
                IssueSeverity.MEDIUM,
                "items.line_total",
                "Line has no total.",
                item.printed_name,
            )
        elif item.unit_price is not None:
            expected = round2(item.quantity * item.unit_price - item.discount)
            if abs(expected - item.line_total) > TOLERANCE:
                flag(
                    "totals_mismatch",
                    IssueSeverity.MEDIUM,
                    "items.line_total",
                    f"quantity × unit price − discount = {fmt(expected)}, "
                    f"line total is {fmt(item.line_total)}.",
                    item.printed_name,
                )

    # Line totals are after line discounts; totals.discount_total is meant for receipt-wide
    # discounts only, but the model sometimes repeats the line discounts there (printed as a
    # separate "savings" line). Stored values are normalized so that subtotal − discount_total =
    # total: subtotal before any discount, discount_total all discounts.
    lines_sum = (
        round2(sum((it.line_total or Decimal(0) for it in items), Decimal(0)))
        if all(it.line_total is not None for it in items)
        else None
    )
    line_discounts = round2(sum((it.discount for it in items), Decimal(0)))
    receipt_discount = num(totals.get("discount_total")) or Decimal(0)
    if (
        receipt_discount > 0
        and line_discounts > 0
        and abs(receipt_discount - line_discounts) <= TOLERANCE
        and lines_sum is not None
        and total is not None
        and abs(lines_sum - total) <= TOLERANCE
    ):
        receipt_discount = Decimal(0)
    if (
        lines_sum is not None
        and total is not None
        and abs(round2(lines_sum - receipt_discount) - total) > TOLERANCE
    ):
        after = (
            f" (minus receipt discount: {fmt(round2(lines_sum - receipt_discount))})"
            if receipt_discount
            else ""
        )
        flag(
            "totals_mismatch",
            IssueSeverity.HIGH,
            "totals.total",
            f"Lines add up to {fmt(lines_sum)}{after}, receipt total is {fmt(total)}.",
        )
    discount_total = round2(line_discounts + receipt_discount)
    subtotal = (
        round2(lines_sum + line_discounts) if lines_sum is not None else num(totals.get("subtotal"))
    )

    method = clean(payment.get("method"))
    brand = clean(payment.get("card_brand"))
    address = ", ".join(p for p in (clean(store.get("address")), clean(store.get("city"))) if p)
    return Parse(
        is_receipt=True,
        store_key=store_key,
        store_name=store_name,
        store_legal_name=clean(store.get("legal_name")),
        store_address=address or None,
        store_tax_id=clean(store.get("tax_id")),
        purchased_at=purchased,
        receipt_number=clean(receipt.get("number")),
        receipt_key=receipt_key,
        currency=currency,
        subtotal=subtotal,
        discount_total=discount_total,
        tax_total=num(totals.get("tax_total")),
        total=total,
        payment_method=method.lower() if method else None,
        card_brand=brand.upper() if brand else None,
        card_last4=last4,
        items=tuple(items),
        issues=tuple(issues),
        raw_output=raw_output,
        model=model,
        parser_version=parser_version,
    )
