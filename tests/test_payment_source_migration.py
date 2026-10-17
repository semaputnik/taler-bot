"""The migration that lets a card exist without its last four digits (cards added by hand)."""

import asyncio

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from tests.conftest import alembic_config, recreate_database, scratch_url
from tests.test_expense_migration import _diff, _shape_of

BEFORE = "b7d2e4f6a918"

SEED = """
INSERT INTO users (id, is_allowed, timezone, default_currency) VALUES
    (1, true, 'Europe/Madrid', 'EUR'), (2, true, 'Europe/Madrid', 'EUR');
INSERT INTO payment_sources (user_id, kind, name, brand, last4) VALUES
    (1, 'card', 'VISA •0848', 'VISA', '0848'),
    (1, 'cash', 'Cash', NULL, NULL);
"""

HAND_CARD = "INSERT INTO payment_sources (user_id, kind, name) VALUES ({user}, 'card', '{name}')"
CASH_WITH_DIGITS = (
    "INSERT INTO payment_sources (user_id, kind, name, last4) VALUES (2, 'cash', 'Cash', '1234')"
)


async def _run(engine: AsyncEngine, sql: str) -> None:
    async with engine.begin() as conn:
        for statement in sql.split(";\n"):
            if statement.strip():
                await conn.execute(text(statement))


async def _refused(engine: AsyncEngine, sql: str, constraint: str) -> None:
    with pytest.raises(IntegrityError) as raised:
        await _run(engine, sql)
    assert constraint in str(raised.value)


async def _scratch(suffix: str):
    url = scratch_url(suffix)
    await recreate_database(url)
    return alembic_config(url), create_async_engine(url, poolclass=NullPool)


async def test_the_relaxed_check_accepts_a_card_without_digits_and_still_refuses_cash_with_them():
    config, engine = await _scratch("source_migration")
    try:
        await asyncio.to_thread(command.upgrade, config, BEFORE)
        await _run(engine, SEED)
        await _refused(
            engine, HAND_CARD.format(user=1, name="Revolut"), "ck_payment_sources_card_has_last4"
        )

        await asyncio.to_thread(command.upgrade, config, "head")

        await _run(engine, HAND_CARD.format(user=1, name="Revolut"))
        await _run(engine, HAND_CARD.format(user=1, name="N26"))  # several cards may lack digits
        await _refused(engine, CASH_WITH_DIGITS, "ck_payment_sources_card_has_last4")
        async with engine.connect() as conn:
            assert await conn.run_sync(lambda c: _diff(c)) == []
    finally:
        await engine.dispose()


async def test_a_source_name_is_unique_per_user_ignoring_case():
    config, engine = await _scratch("source_migration_names")
    try:
        await asyncio.to_thread(command.upgrade, config, "head")
        await _run(engine, SEED)
        await _run(engine, HAND_CARD.format(user=1, name="Revolut"))

        await _refused(
            engine,
            HAND_CARD.format(user=1, name="REVOLUT"),
            "uq_payment_sources_user_id_lower_name",
        )
        await _refused(
            engine, HAND_CARD.format(user=1, name="cash"), "uq_payment_sources_user_id_lower_name"
        )
        await _run(engine, HAND_CARD.format(user=2, name="Revolut"))  # another user's name is free
    finally:
        await engine.dispose()


async def test_the_downgrade_without_hand_added_cards_restores_the_old_schema():
    config, engine = await _scratch("source_migration_down")
    try:
        await asyncio.to_thread(command.upgrade, config, BEFORE)
        old_shape = await _shape_of(engine)
        await _run(engine, SEED)
        await asyncio.to_thread(command.upgrade, config, "head")
        assert await _shape_of(engine) != old_shape

        await asyncio.to_thread(command.downgrade, config, BEFORE)

        assert await _shape_of(engine) == old_shape
        await _refused(
            engine, HAND_CARD.format(user=1, name="Revolut"), "ck_payment_sources_card_has_last4"
        )
        await asyncio.to_thread(command.upgrade, config, "head")  # and forward again
    finally:
        await engine.dispose()


async def test_a_hand_added_card_blocks_the_downgrade():
    config, engine = await _scratch("source_migration_blocked")
    try:
        await asyncio.to_thread(command.upgrade, config, "head")
        await _run(engine, SEED)
        await _run(engine, HAND_CARD.format(user=1, name="Revolut"))

        with pytest.raises((DBAPIError, IntegrityError)):
            await asyncio.to_thread(command.downgrade, config, BEFORE)
    finally:
        await engine.dispose()
