from sqlalchemy import delete, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.mapping import expense as mapping
from src.database.models import Expense as ExpenseRow
from src.database.models import ExpenseTag, Payee, Tag
from src.database.models import PaymentSource as SourceRow
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

    async def _load(self, condition) -> Expense | None:
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

    async def _values(self, expense: Expense) -> dict:
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
