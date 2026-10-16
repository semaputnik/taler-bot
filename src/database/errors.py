from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.exc import IntegrityError

from src.exception import (
    CheckViolationError,
    DatabaseException,
    ForeignKeyViolationError,
    UniqueViolationError,
)

# PostgreSQL SQLSTATE codes of integrity constraint violations.
_BY_SQLSTATE: dict[str, type[DatabaseException]] = {
    "23505": UniqueViolationError,
    "23503": ForeignKeyViolationError,
    "23514": CheckViolationError,
}


@contextmanager
def translate_db_errors() -> Iterator[None]:
    """Turn SQLAlchemy integrity errors into app exceptions; they never leave `database`."""
    try:
        yield
    except IntegrityError as error:
        sqlstate = getattr(error.orig, "sqlstate", None)
        raise _BY_SQLSTATE.get(sqlstate, DatabaseException)(str(error.orig)) from error
