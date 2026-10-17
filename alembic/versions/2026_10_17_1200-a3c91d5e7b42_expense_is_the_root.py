"""expense is the root

Revision ID: a3c91d5e7b42
Revises: e02931db5f10
Create Date: 2026-10-17 12:00:00.000000

ADR-0003. Hand-written: autogenerate would drop `stores` and create `payees` instead of
renaming it, and it does not write the data step.

Schema: `stores` becomes `payees` (`store_key` -> `payee_key`, and the `store_id` columns of
`receipts` and `store_products` -> `payee_id`, constraints and indexes renamed with them); new
`payment_sources`, `expenses`, `tags`, `expense_tags`.

Data: one cash source for every user that has a receipt without a card ending; one card for
every distinct (user, card ending), branded with the most frequent brand (ties: alphabetical,
so a rerun on a copy gives the same result); one expense for every receipt, whatever its
status. `receipts.card_brand` and `card_last4` stay as printed.

Downgrade drops the new tables and renames back. The receipt tables are untouched by the data
step, so nothing is lost; expenses, cards and tags created after the upgrade are.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3c91d5e7b42"
down_revision: str | Sequence[str] | None = "e02931db5f10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EXPENSE_CATEGORIES = (
    "'groceries', 'restaurants', 'transport', 'rent', 'utilities', 'health', "
    "'entertainment', 'subscriptions', 'clothing', 'travel', 'gifts', 'other'"
)

# (table, old name, new name) of the constraints and indexes the rename touches.
CONSTRAINT_RENAMES = (
    ("payees", "pk_stores", "pk_payees"),
    ("payees", "uq_stores_user_id_store_key", "uq_payees_user_id_payee_key"),
    ("payees", "fk_stores_user_id_users", "fk_payees_user_id_users"),
    ("receipts", "fk_receipts_store_id_stores", "fk_receipts_payee_id_payees"),
    ("store_products", "fk_store_products_store_id_stores", "fk_store_products_payee_id_payees"),
)
INDEX_RENAMES = (
    ("ix_receipts_user_id_store_id_purchased_at", "ix_receipts_user_id_payee_id_purchased_at"),
    ("ix_store_products_store_id", "ix_store_products_payee_id"),
)


def _rename(old_table: str, new_table: str, old_column: str, new_column: str, reverse: bool):
    """Rename `stores` <-> `payees` and the key columns; `reverse` goes back."""
    if reverse:
        old_table, new_table = new_table, old_table
        old_column, new_column = new_column, old_column
    op.rename_table(old_table, new_table)
    op.alter_column(new_table, old_column, new_column_name=new_column)
    op.execute(f"ALTER SEQUENCE IF EXISTS {old_table}_id_seq RENAME TO {new_table}_id_seq")


def _rename_references(reverse: bool) -> None:
    """Rename the `store_id` columns and the constraints and indexes named after the old names.
    Runs while the table is called `payees` (after the rename up, before it down)."""
    pairs = [("receipts", "store_id", "payee_id"), ("store_products", "store_id", "payee_id")]
    for table, old, new in pairs:
        if reverse:
            old, new = new, old
        op.alter_column(table, old, new_column_name=new)
    for table, old, new in CONSTRAINT_RENAMES:
        if reverse:
            old, new = new, old
        op.execute(f'ALTER TABLE "{table}" RENAME CONSTRAINT "{old}" TO "{new}"')
    for old, new in INDEX_RENAMES:
        if reverse:
            old, new = new, old
        op.execute(f'ALTER INDEX "{old}" RENAME TO "{new}"')


def upgrade() -> None:
    """Upgrade schema."""
    # --- stores become payees --------------------------------------------------------
    _rename("stores", "payees", "store_key", "payee_key", reverse=False)
    _rename_references(reverse=False)

    # --- new tables ------------------------------------------------------------------
    op.create_table(
        "payment_sources",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("brand", sa.String(), nullable=True),
        sa.Column("last4", sa.CHAR(length=4), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("kind IN ('card', 'cash')", name=op.f("ck_payment_sources_kind")),
        sa.CheckConstraint("last4 ~ '^[0-9]{4}$'", name=op.f("ck_payment_sources_last4")),
        sa.CheckConstraint(
            "(kind = 'card') = (last4 IS NOT NULL)", name=op.f("ck_payment_sources_card_has_last4")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_payment_sources_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payment_sources")),
        sa.UniqueConstraint("user_id", "last4", name=op.f("uq_payment_sources_user_id_last4")),
    )
    op.create_index(
        "uq_payment_sources_user_id_cash",
        "payment_sources",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'cash'"),
    )

    op.create_table(
        "expenses",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.CHAR(length=3), nullable=False),
        sa.Column("spent_at", sa.Date(), nullable=False),
        sa.Column("payee_id", sa.BigInteger(), nullable=True),
        sa.Column("payment_source_id", sa.BigInteger(), nullable=True),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("receipt_id", sa.BigInteger(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            f"category IN ({EXPENSE_CATEGORIES})", name=op.f("ck_expenses_category")
        ),
        sa.CheckConstraint("amount >= 0", name=op.f("ck_expenses_amount")),
        sa.ForeignKeyConstraint(
            ["payee_id"],
            ["payees.id"],
            name=op.f("fk_expenses_payee_id_payees"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["payment_source_id"],
            ["payment_sources.id"],
            name=op.f("fk_expenses_payment_source_id_payment_sources"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["receipt_id"],
            ["receipts.id"],
            name=op.f("fk_expenses_receipt_id_receipts"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_expenses_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_expenses")),
        sa.UniqueConstraint("receipt_id", name=op.f("uq_expenses_receipt_id")),
    )
    op.create_index("ix_expenses_user_id_spent_at", "expenses", ["user_id", "spent_at"])
    op.create_index(
        "ix_expenses_user_id_payee_id_spent_at", "expenses", ["user_id", "payee_id", "spent_at"]
    )
    op.create_index(
        "ix_expenses_user_id_payment_source_id", "expenses", ["user_id", "payment_source_id"]
    )

    op.create_table(
        "tags",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("char_length(name) BETWEEN 1 AND 32", name=op.f("ck_tags_name_length")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_tags_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tags")),
        sa.UniqueConstraint("user_id", "name", name=op.f("uq_tags_user_id_name")),
    )

    op.create_table(
        "expense_tags",
        sa.Column("expense_id", sa.BigInteger(), nullable=False),
        sa.Column("tag_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["expense_id"],
            ["expenses.id"],
            name=op.f("fk_expense_tags_expense_id_expenses"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tag_id"], ["tags.id"], name=op.f("fk_expense_tags_tag_id_tags"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("expense_id", "tag_id", name=op.f("pk_expense_tags")),
    )
    op.create_index("ix_expense_tags_tag_id", "expense_tags", ["tag_id"])

    # --- data: cash sources, cards, one expense per receipt --------------------------
    op.execute(
        """
        INSERT INTO payment_sources (user_id, kind, name)
        SELECT DISTINCT user_id, 'cash', 'Cash'
        FROM receipts
        WHERE card_last4 IS NULL
        ORDER BY user_id
        """
    )
    # The brand is the most frequent one among the receipts with this ending (non-empty first,
    # ties broken alphabetically); its name is "BRAND •1234", or "•1234" without a brand.
    op.execute(
        """
        INSERT INTO payment_sources (user_id, kind, name, brand, last4)
        SELECT user_id, 'card',
               CASE WHEN brand IS NULL THEN '•' || last4 ELSE brand || ' •' || last4 END,
               brand, last4
        FROM (
            SELECT DISTINCT ON (user_id, card_last4)
                   user_id, card_last4 AS last4, brand
            FROM (
                SELECT user_id, card_last4,
                       NULLIF(upper(btrim(card_brand)), '') AS brand,
                       count(*) AS n
                FROM receipts
                WHERE card_last4 IS NOT NULL
                GROUP BY user_id, card_last4, NULLIF(upper(btrim(card_brand)), '')
            ) counted
            ORDER BY user_id, card_last4, (brand IS NULL), n DESC, brand
        ) chosen
        ORDER BY user_id, last4
        """
    )
    op.execute(
        """
        INSERT INTO expenses (
            user_id, amount, currency, spent_at, payee_id, payment_source_id, category,
            receipt_id, deleted_at, created_at, updated_at
        )
        SELECT r.user_id,
               GREATEST(COALESCE(r.total, 0), 0),
               COALESCE(r.currency, u.default_currency),
               (COALESCE(r.purchased_at, p.received_at, r.created_at) AT TIME ZONE u.timezone)::date,
               r.payee_id,
               s.id,
               'groceries',
               r.id,
               r.deleted_at,
               r.created_at,
               r.updated_at
        FROM receipts r
        JOIN users u ON u.id = r.user_id
        LEFT JOIN receipt_photos p ON p.receipt_id = r.id
        LEFT JOIN payment_sources s
               ON s.user_id = r.user_id
              AND ((r.card_last4 IS NULL AND s.kind = 'cash') OR s.last4 = r.card_last4)
        ORDER BY r.id
        """
    )


def downgrade() -> None:
    """Downgrade schema. Expenses, cards and tags are dropped; the receipt tables keep all
    they had, so the old shape comes back whole."""
    op.drop_index("ix_expense_tags_tag_id", table_name="expense_tags")
    op.drop_table("expense_tags")
    op.drop_table("tags")
    op.drop_index("ix_expenses_user_id_payment_source_id", table_name="expenses")
    op.drop_index("ix_expenses_user_id_payee_id_spent_at", table_name="expenses")
    op.drop_index("ix_expenses_user_id_spent_at", table_name="expenses")
    op.drop_table("expenses")
    op.drop_index(
        "uq_payment_sources_user_id_cash",
        table_name="payment_sources",
        postgresql_where=sa.text("kind = 'cash'"),
    )
    op.drop_table("payment_sources")

    _rename_references(reverse=True)
    _rename("stores", "payees", "store_key", "payee_key", reverse=True)
