"""Cards added by hand: a card needs no last four digits; source names are unique per user.

The CHECK `card_has_last4` (every card has four digits, cash has none) becomes "cash has no
digits": a card the user adds by hand has a name and nothing else, so receipts can never link to
it. The unique `(user_id, last4)` keeps its meaning (NULLs never collide). A new unique index on
`(user_id, lower(name))` keeps the names of one user's sources apart, whatever the case.

The CHECK keeps its name, `ck_payment_sources_card_has_last4`, so the downgrade and the models
refer to one constraint.

Downgrade restores the old CHECK and drops the index. A card without last four digits (added by
hand) violates the old CHECK, so the downgrade fails while one exists: delete it, or give it
digits, first.

Revision ID: c4e8a1b9d3f5
Revises: b7d2e4f6a918
Create Date: 2026-10-17 18:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c4e8a1b9d3f5"
down_revision: str | Sequence[str] | None = "b7d2e4f6a918"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = "(kind = 'card') = (last4 IS NOT NULL)"
NEW = "NOT (kind = 'cash' AND last4 IS NOT NULL)"


def upgrade() -> None:
    op.drop_constraint(op.f("ck_payment_sources_card_has_last4"), "payment_sources", type_="check")
    op.create_check_constraint(op.f("ck_payment_sources_card_has_last4"), "payment_sources", NEW)
    op.execute(
        "CREATE UNIQUE INDEX uq_payment_sources_user_id_lower_name "
        "ON payment_sources (user_id, lower(name))"
    )


def downgrade() -> None:
    op.drop_index("uq_payment_sources_user_id_lower_name", table_name="payment_sources")
    op.drop_constraint(op.f("ck_payment_sources_card_has_last4"), "payment_sources", type_="check")
    op.create_check_constraint(op.f("ck_payment_sources_card_has_last4"), "payment_sources", OLD)
