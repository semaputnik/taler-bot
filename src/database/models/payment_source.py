from sqlalchemy import CHAR, CheckConstraint, ForeignKey, Identity, Index, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from src.database.models.base import Base, Timestamps, enum_check
from src.domain.enums import PaymentSourceKind


class PaymentSource(Timestamps, Base):
    """What a user's money leaves from: a card (brand and last four digits, or only a name when
    added by hand) or their one cash source (ADR-0003). `name` may be changed by hand; the last
    four digits identify a card read from a receipt."""

    __tablename__ = "payment_sources"
    __table_args__ = (
        enum_check("kind", PaymentSourceKind),
        CheckConstraint("last4 ~ '^[0-9]{4}$'", name="last4"),
        # Cash has no digits; a card added by hand has none either. The name is historical.
        CheckConstraint("NOT (kind = 'cash' AND last4 IS NOT NULL)", name="card_has_last4"),
        # NULL last4 (cash, hand-added cards) never collides: "one card per ending".
        UniqueConstraint("user_id", "last4"),
        # A user's source names differ ignoring case.
        Index("uq_payment_sources_user_id_lower_name", "user_id", text("lower(name)"), unique=True),
        # Exactly one cash source per user.
        Index(
            "uq_payment_sources_user_id_cash",
            "user_id",
            unique=True,
            postgresql_where=text("kind = 'cash'"),
        ),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str]
    name: Mapped[str]
    brand: Mapped[str | None]
    last4: Mapped[str | None] = mapped_column(CHAR(4))
