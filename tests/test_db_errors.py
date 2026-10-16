import pytest
from sqlalchemy.exc import DataError, DBAPIError, OperationalError, SQLAlchemyError

from src.database.errors import translate_db_error
from src.exception import (
    CheckViolationError,
    DatabaseException,
    DataViolationError,
    ForeignKeyViolationError,
    UniqueViolationError,
)


class FakeContext:
    """Stands in for SQLAlchemy's ExceptionContext, which only carries the driver error."""

    def __init__(self, original_exception: Exception) -> None:
        self.original_exception = original_exception
        self.sqlalchemy_exception = DBAPIError("stmt", {}, original_exception)
        self.is_pre_ping = False


class FakeDriverError(Exception):
    def __init__(self, sqlstate: str) -> None:
        super().__init__(sqlstate)
        self.sqlstate = sqlstate


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (DataError("stmt", {}, FakeDriverError("22001")), DataViolationError),
        (OperationalError("stmt", {}, FakeDriverError("08006")), DatabaseException),
    ],
)
def test_other_database_errors_become_app_exceptions(error, expected):
    with pytest.raises(expected) as caught:
        translate_db_error(FakeContext(error.orig))
    assert type(caught.value) is expected


@pytest.mark.parametrize(
    ("sqlstate", "expected"),
    [
        ("23505", UniqueViolationError),
        ("23503", ForeignKeyViolationError),
        ("23514", CheckViolationError),
        ("23502", DatabaseException),
    ],
)
def test_integrity_errors_become_app_exceptions(sqlstate, expected):
    with pytest.raises(expected) as caught:
        translate_db_error(FakeContext(FakeDriverError(sqlstate)))
    assert isinstance(caught.value, DatabaseException)
    assert not isinstance(caught.value, SQLAlchemyError)
