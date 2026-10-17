"""`ExpenseService`: the expense actions the bot offers, and the lists and statistics over
expenses (ADR-0003).

Every write is one Unit of Work: load the aggregate, call one aggregate method, save, commit. An
expense of another user counts as not found (`ExpenseNotFound`). Receipt-backed expenses are
created and kept in step by `ReceiptService`; this service changes only what the user owns
(the category and the tags).
"""

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal
from zoneinfo import ZoneInfo

from src.database.interfaces.uow import UnitOfWork, UnitOfWorkFactory
from src.domain.enums import ExpenseCategory
from src.domain.expense import Expense
from src.exception import ExpenseNotFound, InvalidEdit, UserNotFound
from src.services import periods
from src.services.results import (
    PAGE_SIZE,
    Amount,
    Compared,
    ComparedBlock,
    CurrencyBlock,
    ExpenseCard,
    HistoryPage,
    SpendingReport,
)

_PAYEES_SHOWN = 5
_NOT_ITEMISED = "not_itemised"
_NOT_ITEMISED_FROM = Decimal("0.01")


class ExpenseService:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    # --- one expense -------------------------------------------------------------------

    async def card(self, user_id: int, expense_id: int) -> ExpenseCard:
        """The expense as the user sees it; a deleted expense still answers (`deleted`)."""
        async with self._uow_factory() as uow:
            return await _card(uow, await _load(uow, user_id, expense_id))

    async def for_receipt(self, user_id: int, receipt_id: int) -> ExpenseCard:
        """The expense of one of the user's receipts. `ExpenseNotFound` when the receipt is not
        the user's or is not a purchase (it has no expense)."""
        async with self._uow_factory() as uow:
            expense = await uow.expenses.find_by_receipt(receipt_id)
            if expense is None or expense.user_id != user_id:
                raise ExpenseNotFound(receipt_id)
            return await _card(uow, expense)

    async def set_category(self, user_id: int, expense_id: int, category: str) -> ExpenseCard:
        """Set the expense category from its name (`groceries`, `rent`, ...)."""
        try:
            parsed = ExpenseCategory(category)
        except ValueError:
            raise InvalidEdit(f"unknown expense category {category!r}") from None
        async with self._uow_factory() as uow:
            expense = await _load(uow, user_id, expense_id)
            expense.set_category(parsed)
            await uow.expenses.save(expense)
            await uow.commit()
            return await _card(uow, expense)

    async def set_tags(self, user_id: int, expense_id: int, tags: list[str]) -> ExpenseCard:
        """Replace the expense's tags (stripped, lower-cased, unique, at most ten)."""
        async with self._uow_factory() as uow:
            expense = await _load(uow, user_id, expense_id)
            expense.set_tags(tags)
            await uow.expenses.save(expense)
            await uow.commit()
            return await _card(uow, expense)

    # --- lists and statistics ----------------------------------------------------------

    async def history(
        self, user_id: int, year: int, month: int, payee_id: int | None = None, page: int = 0
    ) -> HistoryPage:
        """One page of the user's month, newest first: the expenses, and the receipts that have
        no expense (failed, not a receipt, duplicate, pending, parsing) so they can be reached.

        A page past the end is the last page. The current month (and later ones) have no later
        month to go to, whatever expenses are dated ahead. A payee that is not the user's
        matches nothing.
        """
        async with self._uow_factory() as uow:
            user = await uow.users.get(user_id)
            if user is None:
                raise UserNotFound(user_id)
            timezone = user.timezone

            async def fetch(number: int) -> HistoryPage:
                return await uow.expenses.history(
                    user_id,
                    year,
                    month,
                    timezone,
                    payee_id=payee_id,
                    offset=number * PAGE_SIZE,
                    limit=PAGE_SIZE,
                )

            found = await fetch(max(page, 0))
            if not found.rows and found.total_rows:
                found = await fetch((found.total_rows - 1) // PAGE_SIZE)
        now = datetime.now(ZoneInfo(timezone))
        if (year, month) >= (now.year, now.month):
            found = found.model_copy(update={"has_later": False})
        return found

    async def spending(
        self, user_id: int, kind: Literal["week", "month"], anchor: date
    ) -> SpendingReport:
        """The week or month of `anchor` (local dates, Monday weeks), against the period before.

        Both periods are read in one Unit of Work: a fixed number of statements. Percentages are
        whole numbers, computed here; blocks are those of the period itself, the user's default
        currency first.
        """
        start, end = periods.period(kind, anchor)
        before_start, before_end = periods.previous(start, end)
        async with self._uow_factory() as uow:
            user = await uow.users.get(user_id)
            if user is None:
                raise UserNotFound(user_id)
            current = await uow.expenses.spending(user_id, start, end)
            before = await uow.expenses.spending(user_id, before_start, before_end)
            earliest = await uow.expenses.earliest_spent_at(user_id)
        today = datetime.now(ZoneInfo(user.timezone)).date()
        earlier = {block.currency: block for block in before.blocks}
        blocks = [_compare(block, earlier.get(block.currency)) for block in current.blocks]
        blocks.sort(key=lambda b: (b.currency != user.default_currency, b.currency))
        return SpendingReport(
            kind=kind,
            start=start,
            end=end,
            is_current=periods.is_current(start, end, today),
            has_earlier=earliest is not None and earliest < start,
            blocks=blocks,
        )


# --- helpers ---------------------------------------------------------------------------


async def _load(uow: UnitOfWork, user_id: int, expense_id: int) -> Expense:
    expense = await uow.expenses.get(expense_id)
    if expense is None or expense.user_id != user_id:
        raise ExpenseNotFound(expense_id)
    return expense


async def _card(uow: UnitOfWork, expense: Expense) -> ExpenseCard:
    catalog = await uow.catalog.get(expense.user_id)
    payee = catalog.payees.get(expense.payee_key) if expense.payee_key is not None else None
    source = (
        catalog.payment_sources.get(expense.payment_source_id)
        if expense.payment_source_id is not None
        else None
    )
    assert expense.id is not None
    return ExpenseCard(
        expense_id=expense.id,
        amount=expense.amount,
        currency=expense.currency,
        spent_at=expense.spent_at,
        payee_name=payee.name if payee is not None else None,
        payment_source_name=source.name if source is not None else None,
        category=str(expense.category),
        tags=list(expense.tags),
        receipt_id=expense.receipt_id,
        deleted=expense.deleted_at is not None,
    )


# --- spending comparison -------------------------------------------------------------------


def _percent(part: Decimal, whole: Decimal) -> int | None:
    """`part` as a whole percent of `whole`, halves rounded up; None when `whole` is zero."""
    if whole == 0:
        return None
    return int((part / whole * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _compared(amounts: list[Amount], total: Decimal, before: list[Amount] | None) -> list[Compared]:
    """Each amount with its share of `total` and its change against the same key in `before`
    (None when there is no earlier period or line)."""
    earlier = {a.key: a.value for a in before or []}
    found = []
    for amount in amounts:
        previous = earlier.get(amount.key)
        found.append(
            Compared(
                key=amount.key,
                label=amount.label,
                value=amount.value,
                share=_percent(amount.value, total) or 0,
                previous=previous,
                change=None
                if previous is None
                else _percent(amount.value - previous, abs(previous)),
            )
        )
    return found


def _compare(block: CurrencyBlock, before: CurrencyBlock | None) -> ComparedBlock:
    products = _compared(block.products, block.total, before.products if before else None)
    if abs(block.not_itemised) >= _NOT_ITEMISED_FROM:
        remainder = Amount(key=_NOT_ITEMISED, label="", value=block.not_itemised)
        previous = (
            [Amount(key=_NOT_ITEMISED, label="", value=before.not_itemised)] if before else None
        )
        products += _compared([remainder], block.total, previous)
    return ComparedBlock(
        currency=block.currency,
        total=block.total,
        previous_total=before.total if before else None,
        change=_percent(block.total - before.total, abs(before.total)) if before else None,
        expense_count=block.expense_count,
        categories=_compared(block.categories, block.total, before.categories if before else None),
        products=products,
        payees=_compared(block.payees, block.total, before.payees if before else None)[
            :_PAYEES_SHOWN
        ],
        sources=_compared(block.sources, block.total, before.sources if before else None),
    )
