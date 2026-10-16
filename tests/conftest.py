"""DB fixtures: a separate `<db>_test` database, migrated once, with each test rolled back."""

import asyncio
from collections.abc import AsyncIterator

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from taler_bot.settings import DatabaseSettings


def _test_url() -> str:
    url = make_url(str(DatabaseSettings().database_url))  # pyright: ignore[reportCallIssue]
    return url.set(database=f"{url.database}_test").render_as_string(hide_password=False)


async def _recreate_database(url: str) -> None:
    target = make_url(url)
    admin = await asyncpg.connect(
        user=target.username,
        password=target.password,
        host=target.host,
        port=target.port,
        database="postgres",
    )
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{target.database}" WITH (FORCE)')
        await admin.execute(f'CREATE DATABASE "{target.database}"')
    finally:
        await admin.close()


@pytest.fixture(scope="session")
async def engine() -> AsyncIterator[AsyncEngine]:
    url = _test_url()
    await _recreate_database(url)
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    # env.py calls asyncio.run, which cannot nest inside the test loop.
    await asyncio.to_thread(command.upgrade, config, "head")

    engine = create_async_engine(url)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    async with engine.connect() as conn:
        transaction = await conn.begin()
        # Commits inside a test become savepoints, so the outer rollback undoes everything.
        async with AsyncSession(bind=conn, join_transaction_mode="create_savepoint") as session:
            yield session
        await transaction.rollback()
