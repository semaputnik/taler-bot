"""ORM rows <-> the `Expense` aggregate. ORM objects never leave the `database` package."""

from collections.abc import Sequence
from typing import Any

from src.database.models import Expense as ExpenseRow
from src.domain.enums import ExpenseCategory
from src.domain.expense import Expense


def expense_values(expense: Expense, *, payee_id: int | None) -> dict[str, Any]:
    """The `expenses` row of the aggregate (everything but its own id and timestamps)."""
    return {
        "user_id": expense.user_id,
        "amount": expense.amount,
        "currency": expense.currency,
        "spent_at": expense.spent_at,
        "payee_id": payee_id,
        "payment_source_id": expense.payment_source_id,
        "category": str(expense.category),  # the database CHECK decides what is valid
        "receipt_id": expense.receipt_id,
        "deleted_at": expense.deleted_at,
    }


def expense_from_rows(row: ExpenseRow, payee_key: str | None, tags: Sequence[str]) -> Expense:
    return Expense(
        id=row.id,
        user_id=row.user_id,
        amount=row.amount,
        currency=row.currency,
        spent_at=row.spent_at,
        payee_key=payee_key,
        payment_source_id=row.payment_source_id,
        category=ExpenseCategory(row.category),
        tags=list(tags),
        receipt_id=row.receipt_id,
        deleted_at=row.deleted_at,
        created_at=row.created_at,
    )
