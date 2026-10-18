"""`ExpenseService`: the expense actions the bot offers, and the lists and statistics over
expenses (ADR-0003).

Every write is one Unit of Work: load the aggregate, call one aggregate method, save, commit. An
expense of another user counts as not found (`ExpenseNotFound`). Receipt-backed expenses are
created and kept in step by `ReceiptService`; this service changes only what the user owns
(the category and the tags), and the facts of an expense the user typed.
"""

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal
from zoneinfo import ZoneInfo

from src.database.interfaces.uow import UnitOfWork, UnitOfWorkFactory
from src.domain.catalog import Catalog, PaymentSource
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
    ExpenseDraft,
    HistoryPage,
    PayeeOption,
    SourceOption,
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

    async def add_manual(self, user_id: int, draft: ExpenseDraft) -> ExpenseCard:
        """Record an expense the user typed, in the user's default currency.

        One Unit of Work: the payee (a known key, or a typed name that is reused when its slug
        exists) and the source (an id, cash, or a new card) are resolved in the catalog, the
        catalog is saved first (new parts get their ids; the expense refers to them), then the
        expense is added. Nothing stays if any step fails.
        """
        category = _category(draft.category)
        async with self._uow_factory() as uow:
            user = await uow.users.get(user_id)
            if user is None:
                raise UserNotFound(user_id)
            catalog = await uow.catalog.get(user_id)
            payee_key = _payee_key(catalog, draft.payee_key, draft.payee_name)
            source = _source(catalog, draft.payment_source_id, draft.cash, draft.new_card_name)
            await uow.catalog.save(catalog)
            expense = Expense.start_manual(
                user_id,
                amount=draft.amount,
                currency=user.default_currency,
                spent_at=draft.spent_at,
                category=category,
                payee_key=payee_key,
                payment_source_id=source.id if source is not None else None,
                tags=list(draft.tags),
            )
            await uow.expenses.add(expense)
            await uow.commit()
            return await _card(uow, expense)

    async def set_amount(self, user_id: int, expense_id: int, amount: Decimal) -> ExpenseCard:
        """Change the amount of an expense the user typed (above zero, in cents)."""
        async with self._uow_factory() as uow:
            expense = await _load(uow, user_id, expense_id)
            expense.set_amount(amount)
            await uow.expenses.save(expense)
            await uow.commit()
            return await _card(uow, expense)

    async def set_payee(
        self,
        user_id: int,
        expense_id: int,
        *,
        payee_key: str | None = None,
        payee_name: str | None = None,
    ) -> ExpenseCard:
        """Change the payee of an expense the user typed: a known key, or a typed name (an
        existing payee with the same slug is reused). Exactly one of the two."""
        if (payee_key is None) == (payee_name is None):
            raise InvalidEdit("give a payee key or a payee name")
        async with self._uow_factory() as uow:
            expense = await _load(uow, user_id, expense_id)
            catalog = await uow.catalog.get(user_id)
            key = _payee_key(catalog, payee_key, payee_name)
            await uow.catalog.save(catalog)
            expense.set_payee(key)
            await uow.expenses.save(expense)
            await uow.commit()
            return await _card(uow, expense)

    async def set_source(
        self,
        user_id: int,
        expense_id: int,
        *,
        source_id: int | None = None,
        cash: bool = False,
        new_card_name: str | None = None,
    ) -> ExpenseCard:
        """Change the payment source of an expense the user typed: one of the user's sources
        by id, their cash, or a new card. Exactly one of the three."""
        if (source_id is not None) + cash + (new_card_name is not None) != 1:
            raise InvalidEdit("give a source id, cash, or a new card name")
        async with self._uow_factory() as uow:
            expense = await _load(uow, user_id, expense_id)
            catalog = await uow.catalog.get(user_id)
            source = _source(catalog, source_id, cash, new_card_name)
            await uow.catalog.save(catalog)
            expense.set_source(source.id if source is not None else None)
            await uow.expenses.save(expense)
            await uow.commit()
            return await _card(uow, expense)

    async def set_date(self, user_id: int, expense_id: int, spent_at: date) -> ExpenseCard:
        """Change the day of an expense the user typed (the user's local day)."""
        async with self._uow_factory() as uow:
            expense = await _load(uow, user_id, expense_id)
            expense.set_date(spent_at)
            await uow.expenses.save(expense)
            await uow.commit()
            return await _card(uow, expense)

    async def soft_delete(self, user_id: int, expense_id: int) -> ExpenseCard:
        """Delete an expense the user typed; it leaves lists and statistics. One with a receipt
        is deleted with its receipt (`ExpenseFollowsReceipt`)."""
        async with self._uow_factory() as uow:
            expense = await _load(uow, user_id, expense_id)
            expense.delete_by_hand()
            await uow.expenses.save(expense)
            await uow.commit()
            return await _card(uow, expense)

    async def recent_payees(self, user_id: int, limit: int = _PAYEES_SHOWN) -> list[PayeeOption]:
        """The payees of the user's latest expenses, newest first, for the entry's first step."""
        async with self._uow_factory() as uow:
            return await uow.expenses.recent_payees(user_id, limit)

    async def payment_sources(self, user_id: int) -> list[SourceOption]:
        """The user's cash first, then their cards by name."""
        async with self._uow_factory() as uow:
            return await uow.catalog.payment_sources(user_id)

    async def set_category(self, user_id: int, expense_id: int, category: str) -> ExpenseCard:
        """Set the expense category from its name (`groceries`, `rent`, ...)."""
        parsed = _category(category)
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


def _category(value: str) -> ExpenseCategory:
    try:
        return ExpenseCategory(value)
    except ValueError:
        raise InvalidEdit(f"unknown expense category {value!r}") from None


def _payee_key(catalog: Catalog, payee_key: str | None, payee_name: str | None) -> str | None:
    """The key of the payee a key or a typed name points at (created for a new name); None for
    neither. A key must be one of the user's payees."""
    if payee_key is not None and payee_name is not None:
        raise InvalidEdit("give a payee key or a payee name, not both")
    if payee_key is not None:
        return catalog.payee(payee_key).payee_key
    if payee_name is not None:
        return catalog.ensure_payee_named(payee_name).payee_key
    return None


def _source(
    catalog: Catalog, source_id: int | None, cash: bool, new_card_name: str | None
) -> PaymentSource | None:
    """The source an id, cash or a new card name points at (created when new); None for none.
    Its id is known once the catalog is saved."""
    if (source_id is not None) + cash + (new_card_name is not None) > 1:
        raise InvalidEdit("give one payment source: an id, cash, or a new card name")
    if source_id is not None:
        return catalog.source(source_id)
    if cash:
        return catalog.cash()
    if new_card_name is not None:
        return catalog.add_card(new_card_name)
    return None


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
        payee_key=payee.payee_key if payee is not None else None,
        payee_name=payee.name if payee is not None else None,
        payment_source_id=source.id if source is not None else None,
        payment_source_name=source.name if source is not None else None,
        category=str(expense.category),
        tags=list(expense.tags),
        receipt_id=expense.receipt_id,
        can_edit_facts=expense.receipt_id is None,
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
