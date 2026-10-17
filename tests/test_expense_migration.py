"""The expense migration (ADR-0003) on a database that already holds receipts."""

import asyncio
from datetime import date
from decimal import Decimal

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from src.database.models import Base
from tests.conftest import alembic_config, recreate_database, scratch_url

BEFORE = "e02931db5f10"
D = Decimal

SEED = """
INSERT INTO users (id, is_allowed, timezone, default_currency) VALUES
    (1, true, 'Europe/Madrid', 'EUR'),
    (2, true, 'America/New_York', 'USD');
INSERT INTO stores (id, user_id, store_key, name) VALUES (10, 1, 'lidl', 'Lidl');
-- user 1
INSERT INTO receipts (id, user_id, status, store_id, total, currency, purchased_at,
                      card_brand, card_last4, deleted_at) VALUES
    (1, 1, 'parsed', 10, 47.50, 'EUR', '2026-10-14 23:30+00', 'VISA', '0848', NULL),
    (2, 1, 'parsed', NULL, 10.00, NULL, NULL, NULL, NULL, NULL),
    (3, 1, 'parsed', 10, 5.25, 'EUR', '2026-09-01 10:00+00', 'visa ', '0848',
     '2026-09-02 08:00+00'),
    (4, 1, 'parsed', NULL, 3.00, 'EUR', '2026-09-03 10:00+00', NULL, '1111', NULL),
    (5, 1, 'failed', NULL, NULL, NULL, NULL, NULL, NULL, NULL),
    (6, 1, 'parsed', NULL, 8.00, 'EUR', '2026-09-04 10:00+00', 'MC', '0848', NULL);
-- user 2
INSERT INTO receipts (id, user_id, status, total, currency, purchased_at, card_brand, card_last4)
VALUES (7, 2, 'parsed', 20.00, NULL, '2026-10-14 03:30+00', 'AMEX', '1111');
INSERT INTO receipt_photos (receipt_id, user_id, path, received_at)
SELECT id, user_id, 'p' || id || '.jpg',
       CASE id WHEN 2 THEN timestamptz '2026-10-20 22:30+00'
                ELSE timestamptz '2026-10-14 10:00+00' END
FROM receipts;
INSERT INTO store_products (id, user_id, store_id, product_key, name, name_raw, category)
VALUES (100, 1, 10, 'lidl::pan', 'Bread', 'PAN', 'bakery');
"""


PAYMENT_SOURCES = "SELECT id, user_id, kind, name, brand, last4 FROM payment_sources ORDER BY id"
EXPENSES = (
    "SELECT id, user_id, amount, currency, spent_at, payee_id, payment_source_id, category, "
    "receipt_id, deleted_at FROM expenses ORDER BY id"
)


def _shape(connection: Connection) -> dict:
    """Tables, columns, keys, indexes and checks: what a migration must restore exactly."""
    inspector = inspect(connection)
    shape = {}
    for table in sorted(inspector.get_table_names()):
        shape[table] = {
            "columns": sorted(
                (c["name"], str(c["type"]), c["nullable"], str(c["default"]))
                for c in inspector.get_columns(table)
            ),
            "pk": inspector.get_pk_constraint(table),
            "fks": sorted(
                (f["name"], tuple(f["constrained_columns"]), f["referred_table"], str(f["options"]))
                for f in inspector.get_foreign_keys(table)
            ),
            "uniques": sorted(
                (u["name"], tuple(u["column_names"]))
                for u in inspector.get_unique_constraints(table)
            ),
            "indexes": sorted(
                (i["name"], tuple(i["column_names"]), i["unique"])
                for i in inspector.get_indexes(table)
            ),
            "checks": sorted(
                (c["name"], c["sqltext"]) for c in inspector.get_check_constraints(table)
            ),
        }
    return shape


def _diff(connection: Connection) -> list:
    context = MigrationContext.configure(connection, opts={"compare_server_default": True})
    return compare_metadata(context, Base.metadata)


async def _shape_of(engine: AsyncEngine) -> dict:
    async with engine.connect() as conn:
        return await conn.run_sync(_shape)


async def _seed(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        for statement in SEED.split(";\n"):
            if statement.strip():
                await conn.execute(text(statement))


async def _rows(engine: AsyncEngine, sql: str) -> list[tuple]:
    async with engine.connect() as conn:
        return [tuple(row) for row in (await conn.execute(text(sql))).all()]


async def test_the_migration_turns_receipts_into_expenses_and_back() -> None:
    url = scratch_url("expense_migration")
    await recreate_database(url)
    config = alembic_config(url)
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        await asyncio.to_thread(command.upgrade, config, BEFORE)
        old_shape = await _shape_of(engine)
        await _seed(engine)
        receipts_before = await _rows(engine, "SELECT * FROM receipts ORDER BY id")
        products_before = await _rows(engine, "SELECT * FROM store_products ORDER BY id")

        await asyncio.to_thread(command.upgrade, config, "head")

        # The store is a payee with its id, key and product.
        assert await _rows(engine, "SELECT id, user_id, payee_key, name FROM payees") == [
            (10, 1, "lidl", "Lidl")
        ]
        assert await _rows(
            engine, "SELECT id, payee_id, product_key, name, category FROM store_products"
        ) == [(100, 10, "lidl::pan", "Bread", "bakery")]
        assert await _rows(
            engine, "SELECT id, payee_id FROM receipts WHERE payee_id IS NOT NULL ORDER BY id"
        ) == [
            (1, 10),
            (3, 10),
        ]

        # One cash source for the user with card-less receipts; one card per ending, branded
        # by the most frequent brand (VISA twice against MC once).
        assert await _rows(
            engine,
            "SELECT user_id, kind, name, brand, last4 FROM payment_sources ORDER BY user_id, id",
        ) == [
            (1, "cash", "Cash", None, None),
            (1, "card", "VISA •0848", "VISA", "0848"),
            (1, "card", "•1111", None, "1111"),
            (2, "card", "AMEX •1111", "AMEX", "1111"),
        ]

        # One expense per receipt, whatever its status; the day is the user's local day.
        expenses = await _rows(
            engine,
            """
            SELECT e.receipt_id, e.user_id, e.amount, e.currency, e.spent_at, e.payee_id,
                   s.name, e.category, e.deleted_at IS NOT NULL
            FROM expenses e LEFT JOIN payment_sources s ON s.id = e.payment_source_id
            ORDER BY e.receipt_id
            """,
        )
        assert expenses == [
            (1, 1, D("47.50"), "EUR", date(2026, 10, 15), 10, "VISA •0848", "groceries", False),
            (2, 1, D("10.00"), "EUR", date(2026, 10, 21), None, "Cash", "groceries", False),
            (3, 1, D("5.25"), "EUR", date(2026, 9, 1), 10, "VISA •0848", "groceries", True),
            (4, 1, D("3.00"), "EUR", date(2026, 9, 3), None, "•1111", "groceries", False),
            (5, 1, D("0.00"), "EUR", date(2026, 10, 14), None, "Cash", "groceries", False),
            (6, 1, D("8.00"), "EUR", date(2026, 9, 4), None, "VISA •0848", "groceries", False),
            (7, 2, D("20.00"), "USD", date(2026, 10, 13), None, "AMEX •1111", "groceries", False),
        ]

        # The receipt tables keep what they held, printed card included.
        receipts_after = await _rows(engine, "SELECT * FROM receipts ORDER BY id")
        assert receipts_after == receipts_before
        async with engine.connect() as conn:
            assert await conn.run_sync(lambda c: _diff(c)) == []

        await asyncio.to_thread(command.downgrade, config, BEFORE)

        assert await _shape_of(engine) == old_shape
        assert await _rows(engine, "SELECT * FROM receipts ORDER BY id") == receipts_before
        assert await _rows(engine, "SELECT * FROM store_products ORDER BY id") == products_before
        assert await _rows(engine, "SELECT id, user_id, store_key, name FROM stores") == [
            (10, 1, "lidl", "Lidl")
        ]

        # And forward again from the downgraded database.
        await asyncio.to_thread(command.upgrade, config, "head")
        assert len(await _rows(engine, "SELECT 1 FROM expenses")) == 7
        async with engine.connect() as conn:
            assert await conn.run_sync(lambda c: _diff(c)) == []
    finally:
        await engine.dispose()


async def test_the_upgrade_is_deterministic_on_a_copy() -> None:
    results = []
    for suffix in ("expense_migration_a", "expense_migration_b"):
        url = scratch_url(suffix)
        await recreate_database(url)
        config = alembic_config(url)
        engine = create_async_engine(url, poolclass=NullPool)
        try:
            await asyncio.to_thread(command.upgrade, config, BEFORE)
            await _seed(engine)
            await asyncio.to_thread(command.upgrade, config, "head")
            results.append(
                (
                    await _rows(engine, PAYMENT_SOURCES),
                    await _rows(engine, EXPENSES),
                )
            )
        finally:
            await engine.dispose()

    assert results[0] == results[1]


async def test_the_upgrade_of_an_empty_database_creates_nothing() -> None:
    url = scratch_url("expense_migration_empty")
    await recreate_database(url)
    config = alembic_config(url)
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        await asyncio.to_thread(command.upgrade, config, "head")
        assert await _rows(engine, "SELECT count(*) FROM expenses") == [(0,)]
        assert await _rows(engine, "SELECT count(*) FROM payment_sources") == [(0,)]
    finally:
        await engine.dispose()
