"""Raw database errors reach callers as app exceptions, whichever way they surface.

The seam is the Unit of Work against a real Postgres: a read, a write and a commit.
"""

from types import SimpleNamespace

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from src.database.engine import create_engine, install_error_translation
from src.database.errors import translate_db_error
from src.database.uow.sqlalchemy import SqlAlchemyUnitOfWork
from src.domain.receipt import Receipt
from src.exception import DatabaseException, UniqueViolationError
from tests.conftest import scratch_url
from tests.domain.builders import photo
from tests.helpers import MakeUow, add_receipt, add_user


async def test_a_driver_error_on_a_read_is_an_app_exception(make_uow: MakeUow):
    async with make_uow() as uow:
        # Does not fit bigint: the driver rejects the parameter before Postgres sees it.
        with pytest.raises(DatabaseException) as caught:
            await uow.users.get(2**70)
    assert not isinstance(caught.value, SQLAlchemyError)


async def test_a_unique_violation_on_a_write_is_an_app_exception(make_uow: MakeUow):
    await add_user(make_uow)
    await add_receipt(make_uow, Receipt.start(1, photo("AQADabc")))

    with pytest.raises(UniqueViolationError) as caught:
        await add_receipt(make_uow, Receipt.start(1, photo("AQADabc")))
    assert not isinstance(caught.value, SQLAlchemyError)


async def test_a_deferred_constraint_failing_at_commit_is_an_app_exception():
    # Needs a real outer COMMIT: in the rolled-back test connection a commit is only a
    # savepoint release, which never checks deferred constraints.
    engine = create_async_engine(scratch_url(), poolclass=NullPool)
    install_error_translation(engine)
    uow = SqlAlchemyUnitOfWork(async_sessionmaker(engine, class_=AsyncSession))
    try:
        async with uow:
            session = uow._session  # noqa: SLF001  no repository table has a deferred constraint
            await session.execute(
                text("CREATE TEMP TABLE t (n int, UNIQUE (n) DEFERRABLE INITIALLY DEFERRED)")
            )
            await session.execute(text("INSERT INTO t VALUES (1), (1)"))  # accepted until commit
            with pytest.raises(UniqueViolationError) as caught:
                await uow.commit()
        assert not isinstance(caught.value, SQLAlchemyError)
    finally:
        await engine.dispose()


async def test_the_app_engine_translates_errors():
    settings = SimpleNamespace(database=SimpleNamespace(url=scratch_url()))
    engine = create_engine(settings)  # type: ignore[arg-type]
    try:
        assert event.contains(engine.sync_engine, "handle_error", translate_db_error)
    finally:
        await engine.dispose()
