"""Shared constants and scenario helpers for tests: seed data through the Unit of Work.

Later tickets add their seeding helpers here, so tests do not repeat setup code.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from src.database.dto.parse import NewReceiptParseDTO, ReceiptParseDTO
from src.database.dto.receipt import NewReceiptDTO, ReceiptDTO
from src.database.dto.user import NewUserDTO
from src.database.uow.sqlalchemy import SqlAlchemyUnitOfWork
from src.domain.enums import ReceiptStatus

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


async def add_allowed_user(
    make_uow: MakeUow,
    user_id: int = 1,
    *,
    first_name: str | None = "Ann",
    username: str | None = "ann",
) -> None:
    async with make_uow() as uow:
        await uow.users.upsert(NewUserDTO(id=user_id, username=username, first_name=first_name))
        await uow.users.set_allowed(user_id, True)
        await uow.commit()


async def add_parsed_receipt(make_uow: MakeUow) -> tuple[ReceiptDTO, ReceiptParseDTO]:
    """A user (id 1) with a parsed receipt that has one parse."""
    await add_user(make_uow)
    receipt = await add_receipt(make_uow, status=ReceiptStatus.PARSED)
    async with make_uow() as uow:
        parse = await uow.parses.add(
            NewReceiptParseDTO(
                receipt_id=receipt.id, status="ok", parser_version="test", photo_ids=[]
            )
        )
        await uow.commit()
    return receipt, parse
