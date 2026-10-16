from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any

from sqlalchemy import BigInteger, CheckConstraint, DateTime, MetaData, Numeric, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Stable constraint names, so Alembic autogenerate and downgrades can refer to them.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

Money = Annotated[Decimal, mapped_column(Numeric(12, 2))]
Quantity = Annotated[Decimal, mapped_column(Numeric(12, 4))]
Timestamp = Annotated[datetime, mapped_column(DateTime(timezone=True))]


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {
        int: BigInteger,
        datetime: DateTime(timezone=True),
        dict[str, Any]: JSONB,
    }


class CreatedAt:
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Timestamps(CreatedAt):
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


def enum_check(column: str, enum: type[StrEnum], *, nullable: bool = False) -> CheckConstraint:
    """CHECK keeping a varchar column inside a StrEnum; native PG enums are painful to migrate."""
    values = ", ".join(f"'{v}'" for v in enum)
    sql = f"{column} IN ({values})"
    if nullable:
        sql = f"{column} IS NULL OR {sql}"
    return CheckConstraint(sql, name=column)
