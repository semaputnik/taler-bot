from datetime import date
from typing import Protocol

from src.database.read_models import HistoryPage, SpendingPeriod
from src.domain.expense import Expense


class ExpenseRepository(Protocol):
    """Loads and saves the whole `Expense` aggregate, tags included. Never commits."""

    async def get(self, expense_id: int) -> Expense | None:
        """The expense with its tags, soft-deleted included."""
        ...

    async def add(self, expense: Expense) -> Expense:
        """Insert a new expense with its tags and set its id. The payee must be in the
        catalog and the payment source must be the user's own (`ForeignKeyViolationError`)."""
        ...

    async def save(self, expense: Expense) -> None:
        """Update the expense row; rewrite the tag links when `tags_changed`."""
        ...

    async def find_by_receipt(self, receipt_id: int) -> Expense | None:
        """The expense attached to the receipt, soft-deleted included."""
        ...

    async def history(
        self,
        user_id: int,
        year: int,
        month: int,
        payee_id: int | None = None,
        offset: int = 0,
        limit: int = 8,
    ) -> HistoryPage:
        """One page of the user's not deleted expenses of a month, newest first.

        An expense belongs to the month of its `spent_at` (already the user's local day). A
        fixed number of statements, whatever the month's size.
        """
        ...

    async def spending(self, user_id: int, start: date, end: date) -> SpendingPeriod:
        """What the user spent on the local days `[start, end)`, per currency, over the not
        deleted expenses by `spent_at`. A fixed number of statements."""
        ...

    async def earliest_spent_at(self, user_id: int) -> date | None:
        """The day of the user's earliest not deleted expense, if any."""
        ...
