"""one photo and one parse per receipt

Revision ID: e02931db5f10
Revises: fe253b6d0855
Create Date: 2026-10-17 00:04:55.538099

ADR-0002. Autogenerate missed the CHECK constraint changes; they are written by hand, as is
the data handling that lets populated tables upgrade and downgrade.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e02931db5f10"
down_revision: str | Sequence[str] | None = "fe253b6d0855"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_STATUSES = "'pending', 'parsing', 'parsed', 'failed', 'not_receipt', 'awaiting_match', 'merged'"
NEW_STATUSES = "'pending', 'parsing', 'parsed', 'failed', 'not_receipt', 'duplicate'"


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint(op.f("ck_receipts_status"), "receipts", type_="check")
    op.drop_constraint(op.f("ck_receipts_merged_into"), "receipts", type_="check")

    # Reduce existing data to one photo and one parse per receipt.
    # A merged receipt already gave its photo and parse to the receipt it was merged into.
    op.execute("DELETE FROM receipts WHERE status = 'merged'")
    op.execute("UPDATE receipts SET status = 'parsed' WHERE status = 'awaiting_match'")
    # Keep the current parse (else the newest), and the first photo.
    op.execute(
        """
        DELETE FROM receipt_parses p
        WHERE p.id <> COALESCE(
            (SELECT r.current_parse_id FROM receipts r WHERE r.id = p.receipt_id),
            (SELECT max(q.id) FROM receipt_parses q WHERE q.receipt_id = p.receipt_id)
        )
        """
    )
    op.execute(
        """
        DELETE FROM receipt_photos p
        WHERE p.id <> (
            SELECT q.id FROM receipt_photos q
            WHERE q.receipt_id = p.receipt_id ORDER BY q.position, q.id LIMIT 1
        )
        """
    )

    op.drop_index(op.f("ix_receipt_messages_receipt_id"), table_name="receipt_messages")
    op.drop_table("receipt_messages")

    op.drop_index(op.f("ix_receipt_parses_receipt_id"), table_name="receipt_parses")
    op.create_unique_constraint(
        op.f("uq_receipt_parses_receipt_id"), "receipt_parses", ["receipt_id"]
    )
    op.drop_column("receipt_parses", "photo_ids")

    op.drop_index(op.f("ix_receipt_photos_receipt_id"), table_name="receipt_photos")
    op.create_unique_constraint(
        op.f("uq_receipt_photos_receipt_id"), "receipt_photos", ["receipt_id"]
    )
    op.drop_column("receipt_photos", "position")

    # The initial migration created this FK by hand (use_alter), so autogenerate drops it
    # only by name.
    op.drop_constraint(
        op.f("fk_receipts_current_parse_id_receipt_parses"), "receipts", type_="foreignkey"
    )
    op.drop_constraint(op.f("fk_receipts_merged_into_id_receipts"), "receipts", type_="foreignkey")
    op.drop_column("receipts", "current_parse_id")
    op.drop_column("receipts", "merged_into_id")

    op.add_column("receipts", sa.Column("duplicate_of_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        op.f("fk_receipts_duplicate_of_id_receipts"),
        "receipts",
        "receipts",
        ["duplicate_of_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        op.f("ck_receipts_status"), "receipts", f"status IN ({NEW_STATUSES})"
    )
    op.create_check_constraint(
        op.f("ck_receipts_duplicate_of"),
        "receipts",
        "(status = 'duplicate') = (duplicate_of_id IS NOT NULL)",
    )


def downgrade() -> None:
    """Downgrade schema. Photos and parses that upgrade deleted do not come back."""
    op.drop_constraint(op.f("ck_receipts_duplicate_of"), "receipts", type_="check")
    op.drop_constraint(op.f("ck_receipts_status"), "receipts", type_="check")

    op.add_column("receipts", sa.Column("merged_into_id", sa.BigInteger(), nullable=True))
    op.add_column("receipts", sa.Column("current_parse_id", sa.BigInteger(), nullable=True))
    # A duplicate becomes a receipt merged into the one it repeated.
    op.execute(
        "UPDATE receipts SET status = 'merged', merged_into_id = duplicate_of_id "
        "WHERE status = 'duplicate'"
    )
    op.drop_constraint(op.f("fk_receipts_duplicate_of_id_receipts"), "receipts", type_="foreignkey")
    op.drop_column("receipts", "duplicate_of_id")
    op.create_foreign_key(
        op.f("fk_receipts_merged_into_id_receipts"),
        "receipts",
        "receipts",
        ["merged_into_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_check_constraint(
        op.f("ck_receipts_status"), "receipts", f"status IN ({OLD_STATUSES})"
    )
    op.create_check_constraint(
        op.f("ck_receipts_merged_into"),
        "receipts",
        "(status = 'merged') = (merged_into_id IS NOT NULL)",
    )

    op.add_column(
        "receipt_photos",
        sa.Column("position", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
    )
    op.drop_constraint(op.f("uq_receipt_photos_receipt_id"), "receipt_photos", type_="unique")
    op.create_index(
        op.f("ix_receipt_photos_receipt_id"), "receipt_photos", ["receipt_id"], unique=False
    )

    op.add_column(
        "receipt_parses",
        sa.Column("photo_ids", postgresql.ARRAY(sa.BigInteger()), nullable=True),
    )
    op.execute(
        "UPDATE receipt_parses p SET photo_ids = COALESCE("
        "(SELECT array_agg(f.id ORDER BY f.id) FROM receipt_photos f "
        "WHERE f.receipt_id = p.receipt_id), '{}')"
    )
    op.alter_column("receipt_parses", "photo_ids", nullable=False)
    op.drop_constraint(op.f("uq_receipt_parses_receipt_id"), "receipt_parses", type_="unique")
    op.create_index(
        op.f("ix_receipt_parses_receipt_id"), "receipt_parses", ["receipt_id"], unique=False
    )
    op.execute(
        "UPDATE receipts r SET current_parse_id = "
        "(SELECT p.id FROM receipt_parses p WHERE p.receipt_id = r.id)"
    )
    # receipts <-> receipt_parses is a cycle: the FK goes in after both tables exist.
    op.create_foreign_key(
        op.f("fk_receipts_current_parse_id_receipt_parses"),
        "receipts",
        "receipt_parses",
        ["current_parse_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "receipt_messages",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("receipt_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["receipt_id"],
            ["receipts.id"],
            name=op.f("fk_receipt_messages_receipt_id_receipts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_receipt_messages_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "message_id", name=op.f("pk_receipt_messages")),
    )
    op.create_index(
        op.f("ix_receipt_messages_receipt_id"), "receipt_messages", ["receipt_id"], unique=False
    )
