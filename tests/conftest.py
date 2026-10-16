"""DB fixtures: a separate `<db>_test` database, migrated once, with each test rolled back."""

import asyncio
import os
from collections.abc import AsyncIterator, Callable

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    create_async_engine,
)

from src.database.uow.sqlalchemy import SqlAlchemyUnitOfWork
from tests.helpers import MakeUow

# Tests never read the app's env file, so a fresh clone (or CI) runs them as is.
# Point TEST_DATABASE_URL at another server to override; the database name is only a prefix.
DEFAULT_TEST_DATABASE_URL = "postgresql+asyncpg://taler:taler@localhost:5447/taler"


def scratch_url(suffix: str = "test") -> str:
    """URL of a throwaway database named `<db>_<suffix>` on the test server."""
    url = make_url(os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL))
    return url.set(database=f"{url.database}_{suffix}").render_as_string(hide_password=False)


async def recreate_database(url: str) -> None:
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


def alembic_config(url: str) -> Config:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    return config


@pytest.fixture(scope="session")
async def engine() -> AsyncIterator[AsyncEngine]:
    url = scratch_url()
    await recreate_database(url)
    config = alembic_config(url)
    # env.py calls asyncio.run, which cannot nest inside the test loop.
    await asyncio.to_thread(command.upgrade, config, "head")

    engine = create_async_engine(url)
    yield engine
    await engine.dispose()


@pytest.fixture
async def connection(engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    """A connection inside an outer transaction that is rolled back after the test."""
    async with engine.connect() as conn:
        transaction = await conn.begin()
        yield conn
        await transaction.rollback()


@pytest.fixture
def session_factory(connection: AsyncConnection) -> Callable[[], AsyncSession]:
    """Sessions bound to the test connection: commits become savepoints of the outer transaction."""

    def make() -> AsyncSession:
        return AsyncSession(
            bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
        )

    return make


@pytest.fixture
def make_uow(session_factory: Callable[[], AsyncSession]) -> MakeUow:
    return lambda: SqlAlchemyUnitOfWork(session_factory)
