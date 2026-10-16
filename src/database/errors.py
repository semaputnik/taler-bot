from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.exc import DBAPIError

from src.exception import (
    CheckViolationError,
    DatabaseException,
    DataViolationError,
    ForeignKeyViolationError,
    UniqueViolationError,
)

# PostgreSQL SQLSTATE codes of integrity constraint violations.
_BY_SQLSTATE: dict[str, type[DatabaseException]] = {
    "23505": UniqueViolationError,
    "23503": ForeignKeyViolationError,
    # ON DELETE RESTRICT reports its own code, but it is the same kind of failure.
    "23001": ForeignKeyViolationError,
    "23514": CheckViolationError,
}
# SQLSTATE class 22: the value itself is bad (too long, out of range, wrong format).
_DATA_EXCEPTION_CLASS = "22"


@contextmanager
def translate_db_errors() -> Iterator[None]:
    """Turn SQLAlchemy database errors into app exceptions; they never leave `database`."""
    try:
        yield
    except DBAPIError as error:
        sqlstate = getattr(error.orig, "sqlstate", None)
        exc_type = _BY_SQLSTATE.get(sqlstate)
        if exc_type is None:
            is_data = str(sqlstate).startswith(_DATA_EXCEPTION_CLASS)
            exc_type = DataViolationError if is_data else DatabaseException
        raise exc_type(str(error.orig)) from error
