from sqlalchemy import ForeignKey, Identity, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.database.models.base import Base, Timestamps, enum_check
from src.domain.enums import Category


class Store(Timestamps, Base):
    """A shop, keyed per user by the slug of its trading name. `name` may be edited by hand."""

    __tablename__ = "stores"
    __table_args__ = (UniqueConstraint("user_id", "store_key"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    store_key: Mapped[str]
    name: Mapped[str]
    legal_name: Mapped[str | None]
    tax_id: Mapped[str | None]
    address: Mapped[str | None]


class StoreProduct(Timestamps, Base):
    """Per-store product catalogue, keyed by `store_key::slug(printed line text)`.

    Created on first purchase and never overwritten by a parse, so `name` and `category`
    are safe to edit by hand.
    """

    __tablename__ = "store_products"
    __table_args__ = (
        UniqueConstraint("user_id", "product_key"),
        UniqueConstraint("source_ref"),
        enum_check("category", Category),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    product_key: Mapped[str]
    name: Mapped[str]
    name_raw: Mapped[str]
    category: Mapped[str] = mapped_column(server_default=Category.OTHER.value)
    unit: Mapped[str] = mapped_column(server_default="pcs")
    # Lets a refinement delete products that only a misread of this receipt created.
    created_by_receipt_id: Mapped[int | None] = mapped_column(
        ForeignKey("receipts.id", ondelete="SET NULL")
    )
    # "n8n:<row id>" for imported rows, so the import can be rerun safely.
    source_ref: Mapped[str | None]
