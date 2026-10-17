from typing import Protocol

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
