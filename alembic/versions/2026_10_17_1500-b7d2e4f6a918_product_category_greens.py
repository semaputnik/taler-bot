"""Product category `greens`: recreate the store_products.category CHECK.

Revision ID: b7d2e4f6a918
Revises: a3c91d5e7b42
Create Date: 2026-10-17 15:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b7d2e4f6a918"
down_revision: str | Sequence[str] | None = "a3c91d5e7b42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = (
    "category IN ('produce', 'meat', 'fish', 'dairy', 'bakery', 'drinks', 'alcohol', 'snacks', "
    "'frozen', 'pantry', 'household', 'personal_care', 'baby', 'pet', 'other')"
)
NEW = (
    "category IN ('produce', 'greens', 'meat', 'fish', 'dairy', 'bakery', 'drinks', 'alcohol', "
    "'snacks', 'frozen', 'pantry', 'household', 'personal_care', 'baby', 'pet', 'other')"
)


def upgrade() -> None:
    op.drop_constraint(op.f("ck_store_products_category"), "store_products", type_="check")
    op.create_check_constraint(op.f("ck_store_products_category"), "store_products", NEW)


def downgrade() -> None:
    # Products filed under `greens` go back to `produce`, the category they came from.
    op.execute("UPDATE store_products SET category = 'produce' WHERE category = 'greens'")
    op.drop_constraint(op.f("ck_store_products_category"), "store_products", type_="check")
    op.create_check_constraint(op.f("ck_store_products_category"), "store_products", OLD)
