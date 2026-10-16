"""Shared constants and helpers for tests."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from src.database.dto.receipt import NewReceiptDTO, ReceiptDTO
from src.database.dto.user import NewUserDTO
from src.database.uow.sqlalchemy import SqlAlchemyUnitOfWork

NOW = datetime(2026, 10, 14, 18, 32, tzinfo=UTC)

MakeUow = Callable[[], SqlAlchemyUnitOfWork]


async def add_user(make_uow: MakeUow, user_id: int = 1) -> None:
    async with make_uow() as uow:
        await uow.users.upsert(NewUserDTO(id=user_id, username=None, first_name=None))
        await uow.commit()


async def add_receipt(make_uow: MakeUow, user_id: int = 1, **fields: Any) -> ReceiptDTO:
    """Add a receipt in its own Unit of Work: a rejected row poisons the transaction."""
    async with make_uow() as uow:
        receipt = await uow.receipts.add(NewReceiptDTO(user_id=user_id, **fields))
        await uow.commit()
    return receipt
