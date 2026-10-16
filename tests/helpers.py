"""Shared constants and scenario helpers for tests: seed data through the Unit of Work.

Later tickets add their seeding helpers here, so tests do not repeat setup code.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from src.database.dto.store import NewStoreDTO, NewStoreProductDTO
from src.database.dto.user import NewUserDTO
from src.database.uow.sqlalchemy import SqlAlchemyUnitOfWork
from src.domain.parse import Parse
from src.domain.receipt import Receipt

NOW = datetime(2026, 10, 14, 18, 32, tzinfo=UTC)

MakeUow = Callable[[], SqlAlchemyUnitOfWork]


async def add_user(make_uow: MakeUow, user_id: int = 1) -> None:
    async with make_uow() as uow:
        await uow.users.upsert(NewUserDTO(id=user_id, username=None, first_name=None))
        await uow.commit()


async def add_receipt(
    make_uow: MakeUow, receipt: Receipt | None = None, *, user_id: int = 1, **fields: Any
) -> Receipt:
    """Add a receipt (given, or built from `fields`) in its own Unit of Work: a rejected row
    poisons the transaction."""
    receipt = receipt or Receipt(user_id=user_id, **fields)
    async with make_uow() as uow:
        receipt = await uow.receipts.add(receipt)
        await uow.commit()
    return receipt


async def seed_catalog(
    make_uow: MakeUow, *parses: Parse, user_id: int = 1
) -> tuple[dict[str, int], dict[str, int]]:
    """The stores and products the parses' items refer to; items need their product rows.

    Returns the store ids by store key and the product ids by product key.
    """
    async with make_uow() as uow:
        stores: dict[str, int] = {}
        products: dict[str, int] = {}
        for parse in parses:
            if parse.store_key is None:
                continue
            if parse.store_key not in stores:
                store = await uow.stores.add(
                    NewStoreDTO(
                        user_id=user_id,
                        store_key=parse.store_key,
                        name=parse.store_name or parse.store_key,
                    )
                )
                stores[parse.store_key] = store.id
            for item in parse.items:
                if item.product_key in products:
                    continue
                product = await uow.products.add(
                    NewStoreProductDTO(
                        user_id=user_id,
                        store_id=stores[parse.store_key],
                        product_key=item.product_key,
                        name=item.readable_name,
                        name_raw=item.printed_name,
                        category=item.category,
                        unit=item.unit,
                    )
                )
                products[item.product_key] = product.id
        await uow.commit()
    return stores, products


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
