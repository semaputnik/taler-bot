"""Schema-safety tests: models and migrations must agree, and migrations must round-trip."""

import asyncio

from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from alembic import command
from src.database.models import Base
from tests.conftest import recreate_database, scratch_url


def _diff(connection: Connection) -> list:
    context = MigrationContext.configure(connection, opts={"compare_server_default": True})
    return compare_metadata(context, Base.metadata)


async def test_models_match_migrations(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        diff = await conn.run_sync(_diff)

    assert diff == [], "models and migrations drifted; write a migration"


async def test_migration_round_trip() -> None:
    url = scratch_url("migration_roundtrip")
    await recreate_database(url)
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)

    # env.py calls asyncio.run, which cannot nest inside the test loop.
    await asyncio.to_thread(command.upgrade, config, "head")
    await asyncio.to_thread(command.downgrade, config, "base")

    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            leftover = await conn.run_sync(lambda c: set(inspect(c).get_table_names()))
        assert leftover <= {"alembic_version"}

        await asyncio.to_thread(command.upgrade, config, "head")
        async with engine.connect() as conn:
            diff = await conn.run_sync(_diff)
        assert diff == []
    finally:
        await engine.dispose()
