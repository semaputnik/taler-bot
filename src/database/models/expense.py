from datetime import date, datetime

from sqlalchemy import CHAR, CheckConstraint, ForeignKey, Identity, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.database.models.base import Base, Money, Timestamps, enum_check
from src.domain.enums import ExpenseCategory


class Expense(Timestamps, Base):
    """One outflow of money (ADR-0003). The root of everything the bot keeps; a receipt is
    attached through `receipt_id` (at most one receipt per expense)."""

    __tablename__ = "expenses"
    __table_args__ = (
        enum_check("category", ExpenseCategory),
        CheckConstraint("amount >= 0", name="amount"),
        UniqueConstraint("receipt_id"),
        Index("ix_expenses_user_id_spent_at", "user_id", "spent_at"),
        Index("ix_expenses_user_id_payee_id_spent_at", "user_id", "payee_id", "spent_at"),
        Index("ix_expenses_user_id_payment_source_id", "user_id", "payment_source_id"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    amount: Mapped[Money]
    currency: Mapped[str] = mapped_column(CHAR(3))
    # The user's local day.
    spent_at: Mapped[date]
    payee_id: Mapped[int | None] = mapped_column(ForeignKey("payees.id", ondelete="SET NULL"))
    payment_source_id: Mapped[int | None] = mapped_column(
        ForeignKey("payment_sources.id", ondelete="SET NULL")
    )
    category: Mapped[str]
    receipt_id: Mapped[int | None] = mapped_column(ForeignKey("receipts.id", ondelete="SET NULL"))
    deleted_at: Mapped[datetime | None]


class Tag(Timestamps, Base):
    """A free word the user attaches to expenses; unique per user, stored lower-cased."""

    __tablename__ = "tags"
    __table_args__ = (
        UniqueConstraint("user_id", "name"),
        CheckConstraint("char_length(name) BETWEEN 1 AND 32", name="name_length"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str]


class ExpenseTag(Base):
    __tablename__ = "expense_tags"
    __table_args__ = (Index("ix_expense_tags_tag_id", "tag_id"),)

    expense_id: Mapped[int] = mapped_column(
        ForeignKey("expenses.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True)
