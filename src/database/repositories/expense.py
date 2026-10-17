from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    ColumnElement,
    Date,
    Integer,
    Numeric,
    String,
    cast,
    delete,
    exists,
    func,
    insert,
    literal,
    null,
    select,
    union_all,
    update,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.mapping import expense as mapping
from src.database.models import Expense as ExpenseRow
from src.database.models import ExpenseTag, Payee, ReceiptItem, ReceiptPhoto, StoreProduct, Tag
from src.database.models import PaymentSource as SourceRow
from src.database.models import Receipt as ReceiptRow
from src.database.read_models import (
    Amount,
    CurrencyBlock,
    CurrencyTotal,
    HistoryPage,
    HistoryRow,
    PayeeOption,
    SpendingPeriod,
)
from src.domain.enums import PaymentSourceKind
from src.domain.expense import Expense
from src.exception import ForeignKeyViolationError


class SqlAlchemyExpenseRepository:
    """Loads and saves the whole `Expense` aggregate (ADR-0003).

    The aggregate says whether the tags changed (`tags_changed`), so the repository never diffs
    rows. The payee is addressed by its key and the payment source by its id; both must belong
    to the expense's user.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, expense_id: int) -> Expense | None:
        return await self._load(ExpenseRow.id == expense_id)

    async def find_by_receipt(self, receipt_id: int) -> Expense | None:
        return await self._load(ExpenseRow.receipt_id == receipt_id)

    async def add(self, expense: Expense) -> Expense:
        values = await self._values(expense)
        row = (
            await self._session.execute(
                insert(ExpenseRow).values(**values).returning(ExpenseRow.id, ExpenseRow.created_at)
            )
        ).one()
        expense.id, expense.created_at = row.id, row.created_at
        await self._write_tags(expense)
        expense.mark_saved()
        return expense

    async def save(self, expense: Expense) -> None:
        assert expense.id is not None
        await self._session.execute(
            update(ExpenseRow)
            .where(ExpenseRow.id == expense.id)
            .values(**await self._values(expense))
        )
        if expense.tags_changed:
            await self._session.execute(
                delete(ExpenseTag).where(ExpenseTag.expense_id == expense.id)
            )
            await self._write_tags(expense)
        expense.mark_saved()

    # --- read models ---------------------------------------------------------------------

    async def history(
        self,
        user_id: int,
        year: int,
        month: int,
        timezone: str,
        payee_id: int | None = None,
        offset: int = 0,
        limit: int = 8,
    ) -> HistoryPage:
        """Four SELECTs, whatever the month's size: the rows, the counts (with the filter's
        payee name), the totals, the payees.

        The rows are the user's live expenses (by `spent_at`) and the live receipts that have no
        live expense (by `coalesce(purchased_at, received_at)` converted to `timezone`), as one
        union; the totals are over the expenses only.
        """
        start = date(year, month, 1)
        end = date(year + (month == 12), month % 12 + 1, 1)
        mine = (ExpenseRow.user_id == user_id, ExpenseRow.deleted_at.is_(None))
        in_month = (*mine, ExpenseRow.spent_at >= start, ExpenseRow.spent_at < end)
        expense_shown = (
            (*in_month, ExpenseRow.payee_id == payee_id) if payee_id is not None else in_month
        )

        local = func.timezone(
            timezone, func.coalesce(ReceiptRow.purchased_at, ReceiptPhoto.received_at)
        )
        expense_rows = (
            select(
                ExpenseRow.id.label("expense_id"),
                ExpenseRow.receipt_id.label("receipt_id"),
                ExpenseRow.spent_at.label("day"),
                literal(0).label("kind"),
                ExpenseRow.payee_id.label("payee_id"),
                ExpenseRow.amount.label("amount"),
                ExpenseRow.currency.label("currency"),
                ExpenseRow.category.label("category"),
                ReceiptRow.status.label("status"),
                ExpenseRow.id.label("sort_id"),
            )
            .select_from(ExpenseRow)
            .outerjoin(ReceiptRow, ReceiptRow.id == ExpenseRow.receipt_id)
            .where(*mine)
        )
        receipt_rows = (
            select(
                cast(null(), Integer).label("expense_id"),
                ReceiptRow.id.label("receipt_id"),
                cast(local, Date).label("day"),
                literal(1).label("kind"),
                ReceiptRow.payee_id.label("payee_id"),
                cast(null(), Numeric(12, 2)).label("amount"),
                cast(null(), String).label("currency"),
                cast(null(), String).label("category"),
                ReceiptRow.status.label("status"),
                ReceiptRow.id.label("sort_id"),
            )
            .select_from(
                ReceiptRow.__table__.join(ReceiptPhoto, ReceiptPhoto.receipt_id == ReceiptRow.id)
            )
            .where(
                ReceiptRow.user_id == user_id,
                ReceiptRow.deleted_at.is_(None),
                ~exists().where(
                    ExpenseRow.receipt_id == ReceiptRow.id, ExpenseRow.deleted_at.is_(None)
                ),
            )
        )
        union = union_all(expense_rows, receipt_rows).subquery("history_rows")
        in_range = (union.c.day >= start, union.c.day < end)
        shown = (*in_range, union.c.payee_id == payee_id) if payee_id is not None else in_range

        found = await self._session.execute(
            select(
                union.c.expense_id,
                union.c.receipt_id,
                union.c.day,
                Payee.name,
                union.c.amount,
                union.c.currency,
                union.c.category,
                union.c.status,
            )
            .select_from(union.outerjoin(Payee, Payee.id == union.c.payee_id))
            .where(*shown)
            .order_by(union.c.day.desc(), union.c.kind, union.c.sort_id.desc())
            .offset(offset)
            .limit(limit)
        )
        rows = [
            HistoryRow(
                expense_id=expense_id,
                receipt_id=receipt_id,
                has_receipt=receipt_id is not None,
                day=day,
                payee_name=payee_name,
                amount=amount,
                currency=currency,
                category=category,
                status=status,
            )
            for expense_id, receipt_id, day, payee_name, amount, currency, category, status in found
        ]

        filter_name = (
            select(Payee.name)
            .where(Payee.id == payee_id, Payee.user_id == user_id)
            .scalar_subquery()
            if payee_id is not None
            else null()
        )
        total_rows, expense_count, earlier, later, payee_name = (
            await self._session.execute(
                select(
                    func.count().filter(*shown),
                    func.count().filter(*shown, union.c.expense_id.is_not(None)),
                    func.coalesce(func.bool_or(union.c.day < start), False),
                    func.coalesce(func.bool_or(union.c.day >= end), False),
                    filter_name,
                ).select_from(union)
            )
        ).one()
        sums = await self._session.execute(
            select(ExpenseRow.currency, func.sum(ExpenseRow.amount))
            .where(*expense_shown)
            .group_by(ExpenseRow.currency)
            .order_by(ExpenseRow.currency)
        )
        month_payees = await self._session.execute(
            select(Payee.id, Payee.payee_key, Payee.name)
            .where(
                Payee.user_id == user_id,
                exists().where(union.c.payee_id == Payee.id, *in_range),
            )
            .order_by(Payee.name, Payee.id)
        )
        return HistoryPage(
            year=year,
            month=month,
            rows=rows,
            total_rows=total_rows,
            expense_count=expense_count,
            totals=[CurrencyTotal(currency=c, amount=a) for c, a in sums],
            payees=[PayeeOption(payee_id=i, payee_key=k, name=n) for i, k, n in month_payees],
            has_earlier=earlier,
            has_later=later,
            payee_name=payee_name,
        )

    async def recent_payees(self, user_id: int, limit: int) -> list[PayeeOption]:
        """The payees of the user's latest not deleted expenses: one SELECT, ordered by the
        day of each payee's latest expense (newest first), then by name."""
        latest = func.max(ExpenseRow.spent_at)
        found = await self._session.execute(
            select(Payee.id, Payee.payee_key, Payee.name)
            .join(ExpenseRow, ExpenseRow.payee_id == Payee.id)
            .where(
                Payee.user_id == user_id,
                ExpenseRow.user_id == user_id,
                ExpenseRow.deleted_at.is_(None),
            )
            .group_by(Payee.id)
            .order_by(latest.desc(), Payee.name, Payee.id)
            .limit(limit)
        )
        return [PayeeOption(payee_id=i, payee_key=k, name=n) for i, k, n in found]

    async def spending(self, user_id: int, start: date, end: date) -> SpendingPeriod:
        """Five SELECTs, whatever the number of expenses: totals per currency, amounts per
        expense category, item lines per product category, amounts per payee, per source."""
        counted = (
            ExpenseRow.user_id == user_id,
            ExpenseRow.deleted_at.is_(None),
            ExpenseRow.spent_at >= start,
            ExpenseRow.spent_at < end,
        )
        value = func.sum(ExpenseRow.amount)
        totals = await self._session.execute(
            select(
                ExpenseRow.currency,
                value,
                func.count(),
                func.coalesce(value.filter(ExpenseRow.receipt_id.is_not(None)), 0),
            )
            .where(*counted)
            .group_by(ExpenseRow.currency)
        )
        by_currency = {c: (t, n, r) for c, t, n, r in totals}

        kinds = await self._session.execute(
            select(ExpenseRow.currency, ExpenseRow.category, value)
            .where(*counted)
            .group_by(ExpenseRow.currency, ExpenseRow.category)
            .having(value != 0)
        )
        categories: dict[str, list[Amount]] = {}
        for currency, category, amount in kinds:
            categories.setdefault(currency, []).append(
                Amount(key=category, label=category, value=amount)
            )

        lines = await self._session.execute(
            select(ExpenseRow.currency, StoreProduct.category, func.sum(ReceiptItem.line_total))
            .select_from(ReceiptItem)
            .join(ExpenseRow, ExpenseRow.receipt_id == ReceiptItem.receipt_id)
            .join(StoreProduct, StoreProduct.id == ReceiptItem.store_product_id)
            # A receipt without a readable total is an expense of 0.00: its lines would only
            # push `not_itemised` below zero.
            .where(*counted, ExpenseRow.amount > 0)
            .group_by(ExpenseRow.currency, StoreProduct.category)
            .having(func.coalesce(func.sum(ReceiptItem.line_total), 0) != 0)
        )
        products: dict[str, list[Amount]] = {}
        for currency, category, amount in lines:
            products.setdefault(currency, []).append(
                Amount(key=category, label=category, value=amount)
            )

        shops = await self._session.execute(
            select(ExpenseRow.currency, ExpenseRow.payee_id, func.max(Payee.name), value)
            .select_from(ExpenseRow)
            .outerjoin(Payee, Payee.id == ExpenseRow.payee_id)
            .where(*counted)
            .group_by(ExpenseRow.currency, ExpenseRow.payee_id)
        )
        payees: dict[str, list[Amount]] = {}
        for currency, shop_id, name, amount in shops:
            payees.setdefault(currency, []).append(
                Amount(
                    key="none" if shop_id is None else str(shop_id),
                    label=name or "",
                    value=amount,
                )
            )

        paid = await self._session.execute(
            select(
                ExpenseRow.currency,
                ExpenseRow.payment_source_id,
                func.max(SourceRow.kind),
                func.max(SourceRow.last4),
                func.max(SourceRow.name),
                value,
            )
            .select_from(ExpenseRow)
            .outerjoin(SourceRow, SourceRow.id == ExpenseRow.payment_source_id)
            .where(*counted)
            .group_by(ExpenseRow.currency, ExpenseRow.payment_source_id)
        )
        sources: dict[str, list[Amount]] = {}
        for currency, source_id, kind, last4, name, amount in paid:
            if source_id is None:
                line = Amount(key="none", label="", value=amount)
            elif kind == PaymentSourceKind.CASH.value:
                line = Amount(key="cash", label=name, value=amount)
            else:
                line = Amount(key=last4, label=name, value=amount)
            sources.setdefault(currency, []).append(line)

        blocks = []
        for currency in sorted(by_currency):
            total, count, receipt_total = by_currency[currency]
            itemised = sorted(products.get(currency, []), key=_largest_first)
            blocks.append(
                CurrencyBlock(
                    currency=currency,
                    total=total,
                    expense_count=count,
                    categories=sorted(categories.get(currency, []), key=_largest_first),
                    products=itemised,
                    not_itemised=receipt_total - sum((a.value for a in itemised), Decimal(0)),
                    payees=sorted(payees.get(currency, []), key=_largest_first),
                    sources=sorted(sources.get(currency, []), key=_largest_first),
                )
            )
        return SpendingPeriod(start=start, end=end, blocks=blocks)

    async def earliest_spent_at(self, user_id: int) -> date | None:
        return await self._session.scalar(
            select(func.min(ExpenseRow.spent_at)).where(
                ExpenseRow.user_id == user_id, ExpenseRow.deleted_at.is_(None)
            )
        )

    # --- internals -----------------------------------------------------------------------

    async def _load(self, condition: ColumnElement[bool]) -> Expense | None:
        found = (
            await self._session.execute(
                select(ExpenseRow, Payee.payee_key)
                .outerjoin(Payee, Payee.id == ExpenseRow.payee_id)
                .where(condition)
                .execution_options(populate_existing=True)
            )
        ).one_or_none()
        if found is None:
            return None
        row, payee_key = found
        tags = await self._session.scalars(
            select(Tag.name)
            .join(ExpenseTag, ExpenseTag.tag_id == Tag.id)
            .where(ExpenseTag.expense_id == row.id)
            .order_by(Tag.name)
        )
        return mapping.expense_from_rows(row, payee_key, tags.all())

    async def _values(self, expense: Expense) -> dict[str, Any]:
        payee_id = None
        if expense.payee_key is not None:
            payee_id = await self._session.scalar(
                select(Payee.id).where(
                    Payee.user_id == expense.user_id, Payee.payee_key == expense.payee_key
                )
            )
            if payee_id is None:
                raise ForeignKeyViolationError(
                    f"user {expense.user_id} has no payee {expense.payee_key!r}"
                )
        if expense.payment_source_id is not None:
            owned = await self._session.scalar(
                select(SourceRow.id).where(
                    SourceRow.id == expense.payment_source_id, SourceRow.user_id == expense.user_id
                )
            )
            if owned is None:
                raise ForeignKeyViolationError(
                    f"user {expense.user_id} has no payment source {expense.payment_source_id}"
                )
        return mapping.expense_values(expense, payee_id=payee_id)

    async def _write_tags(self, expense: Expense) -> None:
        """Create the missing tags of the user and link them all to the expense."""
        if not expense.tags:
            return
        await self._session.execute(
            pg_insert(Tag)
            .values([{"user_id": expense.user_id, "name": name} for name in expense.tags])
            .on_conflict_do_nothing(index_elements=[Tag.user_id, Tag.name])
        )
        tag_ids = await self._session.scalars(
            select(Tag.id).where(Tag.user_id == expense.user_id, Tag.name.in_(expense.tags))
        )
        await self._session.execute(
            insert(ExpenseTag).values(
                [{"expense_id": expense.id, "tag_id": tag_id} for tag_id in tag_ids]
            )
        )


def _largest_first(amount: Amount) -> tuple[Decimal, str, str]:
    return -amount.value, amount.label, amount.key
