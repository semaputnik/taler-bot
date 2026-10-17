"""Shared constants and scenario helpers for tests: seed data through the Unit of Work.

Later tickets add their seeding helpers here, so tests do not repeat setup code.
"""

from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from src.database.dto.user import NewUserDTO
from src.database.uow.sqlalchemy import SqlAlchemyUnitOfWork
from src.domain.enums import ReceiptStatus
from src.domain.expense import Expense
from src.domain.parse import Parse
from src.domain.receipt import Receipt
from src.services.expense import ExpenseService
from src.services.results import ExpenseCard, ExpenseDraft
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
    make_uow: MakeUow,
    receipt: Receipt | None = None,
    *,
    user_id: int = 1,
    with_expense: bool = True,
    **fields: Any,
) -> Receipt:
    """Add a receipt (given, or built from `fields`) in its own Unit of Work: a rejected row
    poisons the transaction. A parsed receipt gets its expense, as it does in the app."""
    receipt = receipt or Receipt(user_id=user_id, photo=fields.pop("photo", photo()), **fields)
    async with make_uow() as uow:
        receipt = await uow.receipts.add(receipt)
        await uow.commit()
    if with_expense:
        await add_expense_of(make_uow, receipt)
    return receipt


async def add_expense_of(make_uow: MakeUow, receipt: Receipt) -> Expense | None:
    """The expense the app keeps for a stored parsed receipt (deleted with it); none for any
    other status. Its payee and payment source are created as the service does."""
    if receipt.status is not ReceiptStatus.PARSED:
        return None
    assert receipt.id is not None
    async with make_uow() as uow:
        user = await uow.users.get(receipt.user_id)
        assert user is not None
        catalog = await uow.catalog.get(receipt.user_id)
        header = receipt.header
        source = catalog.source_for(header.card_brand, header.card_last4)
        await uow.catalog.save(catalog)
        expense = Expense.from_receipt(
            receipt.user_id,
            receipt.id,
            header,
            payee_key=header.store_key,
            payment_source_id=source.id,
            received_at=receipt.photo.received_at,
            tz=ZoneInfo(user.timezone),
            default_currency=user.default_currency,
        )
        if receipt.deleted_at is not None:
            expense.soft_delete(receipt.deleted_at)
        expense = await uow.expenses.add(expense)
        await uow.commit()
    return expense


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


async def add_manual_expense(
    make_uow: MakeUow,
    user_id: int = 1,
    *,
    amount: str = "10.00",
    spent_at: date | None = None,
    category: str = "groceries",
    payee_name: str | None = "Mercadona",
    new_card_name: str | None = None,
    tags: tuple[str, ...] = (),
) -> ExpenseCard:
    """An expense typed by hand, through the service; paid in cash unless a new card is named."""
    return await ExpenseService(make_uow).add_manual(
        user_id,
        ExpenseDraft(
            amount=Decimal(amount),
            spent_at=spent_at or NOW.date(),
            category=category,
            payee_name=payee_name,
            cash=new_card_name is None,
            new_card_name=new_card_name,
            tags=list(tags),
        ),
    )
