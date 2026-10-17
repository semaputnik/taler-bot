"""The `Expense` aggregate: one outflow of money (ADR-0003).

Percival & Gregory, *Architecture Patterns with Python*, ch. 1 and 7. An expense is the root of
what the bot keeps: amount, currency, the user's local day, payee, payment source, expense
category and tags. It may carry the receipt it was read from (`receipt_id`).

The mirror rule: the amount, currency, day, payee and source of a receipt-backed expense follow
the receipt's header and change only through `sync_with_receipt`; the direct setters refuse
them (`ExpenseFollowsReceipt`). The category and the tags are the user's own and are never
touched by a receipt.

`payee_key` names a payee of the user's catalog; `payment_source_id` is the id of one of the
catalog's payment sources. `None` means none is recorded.

Amounts. A manual expense and `set_amount` need an amount above zero. A receipt may have no
readable total, and then its expense carries 0.00 until the user corrects the receipt, so the
invariant of a stored expense is "not negative".

Tags are kept stripped, lower-cased, unique and sorted: the database has no order for them.

The repository reads `tags_changed` to know whether to rewrite the tag links (the expense row
itself is always updated on `save`) and calls `mark_saved()` afterwards.
"""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, tzinfo
from decimal import Decimal

from src.domain.enums import ExpenseCategory
from src.domain.receipt import Header
from src.exception import ExpenseFollowsReceipt, InvalidExpense

MAX_TAG_LENGTH = 32
MAX_TAGS = 10
_CENT = Decimal("0.01")


def normalize_tags(tags: list[str] | tuple[str, ...]) -> list[str]:
    """Strip, lower-case, drop empty and repeated tags, sort; refuse a too long tag or too many."""
    cleaned = {tag.strip().lower() for tag in tags} - {""}
    for tag in cleaned:
        if len(tag) > MAX_TAG_LENGTH:
            raise InvalidExpense(f"a tag is at most {MAX_TAG_LENGTH} characters: {tag!r}")
    if len(cleaned) > MAX_TAGS:
        raise InvalidExpense(f"an expense has at most {MAX_TAGS} tags")
    return sorted(cleaned)


def _money(amount: Decimal) -> Decimal:
    return amount.quantize(_CENT)


def _currency(currency: str) -> str:
    code = currency.strip().upper()
    if len(code) != 3 or not code.isalpha():
        raise InvalidExpense(f"a currency is three letters, got {currency!r}")
    return code


@dataclass(frozen=True, kw_only=True)
class _ReceiptFacts:
    amount: Decimal
    currency: str
    spent_at: date


def _facts_of(
    header: Header, *, received_at: datetime, tz: tzinfo, default_currency: str
) -> _ReceiptFacts:
    """What the header says about the money: the total (0.00 when unreadable), the currency and
    the user's local day of the purchase (the photo's day when the purchase time is unknown)."""
    total = header.total if header.total is not None and header.total > 0 else Decimal(0)
    when = header.purchased_at or received_at
    return _ReceiptFacts(
        amount=_money(total),
        currency=_currency(header.currency or default_currency),
        spent_at=when.astimezone(tz).date(),
    )


@dataclass(kw_only=True)
class Expense:
    user_id: int
    amount: Decimal
    currency: str
    spent_at: date
    id: int | None = None
    payee_key: str | None = None
    payment_source_id: int | None = None
    category: ExpenseCategory = ExpenseCategory.OTHER
    tags: list[str] = field(default_factory=list)
    receipt_id: int | None = None
    deleted_at: datetime | None = None
    created_at: datetime | None = None

    # Change tracking for the repository (see module docstring); reset by `mark_saved()`.
    tags_changed: bool = field(default=False, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.amount < 0:
            raise InvalidExpense("an amount cannot be negative")
        self.currency = _currency(self.currency)
        self.tags = normalize_tags(self.tags)

    # --- creation ----------------------------------------------------------------------

    @classmethod
    def start_manual(
        cls,
        user_id: int,
        *,
        amount: Decimal,
        currency: str,
        spent_at: date,
        category: ExpenseCategory = ExpenseCategory.OTHER,
        payee_key: str | None = None,
        payment_source_id: int | None = None,
        tags: list[str] | None = None,
    ) -> Expense:
        """An expense typed by the user: the amount must be above zero."""
        amount = _require_positive(amount)
        return cls(
            user_id=user_id,
            amount=amount,
            currency=currency,
            spent_at=spent_at,
            category=category,
            payee_key=payee_key,
            payment_source_id=payment_source_id,
            tags=tags or [],
        )

    @classmethod
    def from_receipt(
        cls,
        user_id: int,
        receipt_id: int,
        header: Header,
        *,
        payee_key: str | None,
        payment_source_id: int | None,
        received_at: datetime,
        tz: tzinfo,
        default_currency: str,
    ) -> Expense:
        """The expense of a receipt, read from its header; it starts as groceries.

        `received_at` is the photo's time, the day used when the header has no purchase time;
        `tz` is the user's time zone; `default_currency` is used when the header has none.
        """
        facts = _facts_of(header, received_at=received_at, tz=tz, default_currency=default_currency)
        return cls(
            user_id=user_id,
            amount=facts.amount,
            currency=facts.currency,
            spent_at=facts.spent_at,
            payee_key=payee_key,
            payment_source_id=payment_source_id,
            category=ExpenseCategory.GROCERIES,
            receipt_id=receipt_id,
        )

    # --- the receipt -------------------------------------------------------------------

    def sync_with_receipt(
        self,
        header: Header,
        *,
        payee_key: str | None,
        payment_source_id: int | None,
        received_at: datetime,
        tz: tzinfo,
        default_currency: str,
    ) -> None:
        """Copy the header's facts: amount, currency, day, payee and source. The category and
        the tags stay as the user set them."""
        self._ensure_open()
        if self.receipt_id is None:
            raise InvalidExpense("only an expense with a receipt follows a receipt")
        facts = _facts_of(header, received_at=received_at, tz=tz, default_currency=default_currency)
        self.amount = facts.amount
        self.currency = facts.currency
        self.spent_at = facts.spent_at
        self.payee_key = payee_key
        self.payment_source_id = payment_source_id

    # --- the user's own facts ----------------------------------------------------------

    def set_category(self, category: ExpenseCategory) -> None:
        self._ensure_open()
        self.category = ExpenseCategory(category)

    def set_tags(self, tags: list[str]) -> None:
        self._ensure_open()
        self.tags = normalize_tags(tags)
        self.tags_changed = True

    # --- facts a receipt owns ----------------------------------------------------------

    def set_amount(self, amount: Decimal) -> None:
        self._ensure_editable("amount")
        self.amount = _require_positive(amount)

    def set_payee(self, payee_key: str | None) -> None:
        self._ensure_editable("payee")
        self.payee_key = payee_key

    def set_source(self, payment_source_id: int | None) -> None:
        self._ensure_editable("payment source")
        self.payment_source_id = payment_source_id

    def set_date(self, spent_at: date) -> None:
        self._ensure_editable("date")
        self.spent_at = spent_at

    def soft_delete(self, at: datetime | None = None) -> None:
        if self.deleted_at is not None:
            raise InvalidExpense("the expense is already deleted")
        self.deleted_at = at or datetime.now(UTC)

    def restore(self) -> None:
        """Reopen a deleted expense, as it was (a receipt that is a purchase again)."""
        if self.deleted_at is None:
            raise InvalidExpense("the expense is not deleted")
        self.deleted_at = None

    # --- for the repository ------------------------------------------------------------

    def mark_saved(self) -> None:
        self.tags_changed = False

    # --- internals ---------------------------------------------------------------------

    def _ensure_open(self) -> None:
        if self.deleted_at is not None:
            raise InvalidExpense("the expense is deleted")

    def _ensure_editable(self, what: str) -> None:
        self._ensure_open()
        if self.receipt_id is not None:
            raise ExpenseFollowsReceipt(f"the {what} comes from the receipt; correct the receipt")


def _require_positive(amount: Decimal) -> Decimal:
    """The amount in cents; a sum that rounds to zero is refused too."""
    cents = _money(amount)
    if cents <= 0:
        raise InvalidExpense("an amount must be above zero")
    return cents
