"""Shared constants and scenario helpers for tests: seed data through the Unit of Work.

Later tickets add their seeding helpers here, so tests do not repeat setup code.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from src.database.dto.parse import NewReceiptParseDTO, ReceiptParseDTO
from src.database.dto.receipt import NewReceiptDTO, NewReceiptItemDTO, ReceiptDTO
from src.database.dto.user import NewUserDTO
from src.database.uow.sqlalchemy import SqlAlchemyUnitOfWork
from src.domain.catalog import Product, Store
from src.domain.enums import Category, ReceiptStatus

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


async def seed_purchase(
    make_uow: MakeUow, **receipt_fields: Any
) -> tuple[Store, Product, ReceiptDTO, int]:
    """A user (id 1) with a catalog (store, product) and a receipt whose only item uses it.

    Returns the store, the product, the receipt and the item id.
    """
    await add_user(make_uow)
    async with make_uow() as uow:
        catalog = await uow.catalog.get(1)
        store = catalog.ensure_store("lidl", "Lidl")
        product = catalog.ensure_product("lidl", "lidl::pan", "PAN", "Pan", Category.BAKERY, "pcs")
        await uow.catalog.save(catalog)
        receipt = await uow.receipts.add(
            NewReceiptDTO(user_id=1, store_id=store.id, **receipt_fields)
        )
        item = await uow.items.add(
            NewReceiptItemDTO(
                receipt_id=receipt.id,
                store_product_id=product.id,
                position=0,
                name_raw="PAN",
                quantity=1,
                unit="pcs",
            )
        )
        await uow.commit()
    return store, product, receipt, item.id
