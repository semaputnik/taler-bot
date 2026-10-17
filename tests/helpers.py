"""Shared constants and scenario helpers for tests: seed data through the Unit of Work.

Later tickets add their seeding helpers here, so tests do not repeat setup code.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from src.database.dto.user import NewUserDTO
from src.database.uow.sqlalchemy import SqlAlchemyUnitOfWork
from src.domain.parse import Parse
from src.domain.receipt import Receipt
from tests.domain.builders import parse, photo, product

NOW = datetime(2026, 10, 14, 18, 32, tzinfo=UTC)

MakeUow = Callable[[], SqlAlchemyUnitOfWork]


async def add_user(make_uow: MakeUow, user_id: int = 1) -> None:
    async with make_uow() as uow:
        await uow.users.upsert(NewUserDTO(id=user_id, username=None, first_name=None))
        await uow.commit()


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


async def add_receipt(
    make_uow: MakeUow, receipt: Receipt | None = None, *, user_id: int = 1, **fields: Any
) -> Receipt:
    """Add a receipt (given, or built from `fields`) in its own Unit of Work: a rejected row
    poisons the transaction."""
    receipt = receipt or Receipt(user_id=user_id, photo=fields.pop("photo", photo()), **fields)
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
        catalog = await uow.catalog.get(user_id)
        for bought in parses:
            if bought.store_key is None:
                continue
            catalog.ensure_payee(bought.store_key, bought.store_name or bought.store_key)
            for item in bought.items:
                catalog.ensure_product(
                    bought.store_key,
                    item.product_key,
                    item.printed_name,
                    item.readable_name,
                    item.category,
                    item.unit,
                )
        await uow.catalog.save(catalog)
        await uow.commit()
    stores = {key: store.id for key, store in catalog.payees.items() if store.id is not None}
    products = {key: p.id for key, p in catalog.products.items() if p.id is not None}
    return stores, products


async def seed_purchase(make_uow: MakeUow, user_id: int = 1) -> tuple[int, int]:
    """A user with a store, a product and a parsed receipt whose only item uses the product.

    Returns the store id and the product id.
    """
    await add_user(make_uow, user_id)
    bought = parse(product("lidl::pan"), store_key="lidl", store_name="Lidl")
    stores, products = await seed_catalog(make_uow, bought, user_id=user_id)
    receipt = Receipt.start(user_id, photo())
    receipt.apply_parse(bought)
    await add_receipt(make_uow, receipt)
    return stores["lidl"], products["lidl::pan"]
