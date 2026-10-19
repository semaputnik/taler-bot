"""Product category `produce` becomes `fruit_and_vegetables`: rename the rows, recreate the CHECK.

Revision ID: d9f3a7c2e481
Revises: c4e8a1b9d3f5
Create Date: 2026-10-19 23:30:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d9f3a7c2e481"
down_revision: str | Sequence[str] | None = "c4e8a1b9d3f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = (
    "category IN ('produce', 'greens', 'meat', 'fish', 'dairy', 'bakery', 'drinks', 'alcohol', "
    "'snacks', 'frozen', 'pantry', 'household', 'personal_care', 'baby', 'pet', 'other')"
)
NEW = (
    "category IN ('fruit_and_vegetables', 'greens', 'meat', 'fish', 'dairy', 'bakery', 'drinks', "
    "'alcohol', 'snacks', 'frozen', 'pantry', 'household', 'personal_care', 'baby', 'pet', 'other')"
)


def upgrade() -> None:
    op.drop_constraint(op.f("ck_store_products_category"), "store_products", type_="check")
    op.execute(
        "UPDATE store_products SET category = 'fruit_and_vegetables' WHERE category = 'produce'"
    )
    op.create_check_constraint(op.f("ck_store_products_category"), "store_products", NEW)


def downgrade() -> None:
    op.drop_constraint(op.f("ck_store_products_category"), "store_products", type_="check")
    op.execute(
        "UPDATE store_products SET category = 'produce' WHERE category = 'fruit_and_vegetables'"
    )
    op.create_check_constraint(op.f("ck_store_products_category"), "store_products", OLD)
