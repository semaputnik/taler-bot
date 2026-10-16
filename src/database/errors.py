from sqlalchemy.engine import ExceptionContext
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


def translate_db_error(ctx: ExceptionContext) -> None:
    """`handle_error` listener: raise the app exception for a failed statement or commit.

    SQLAlchemy calls it for every DBAPI error on the engine, whichever way it surfaced
    (read, write, flush, commit), so repositories and the Unit of Work need no wrappers.
    """
    # Leave programming errors alone, and the pool's pre-ping, which relies on SQLAlchemy's
    # own disconnect handling.
    if ctx.is_pre_ping or not isinstance(ctx.sqlalchemy_exception, DBAPIError):
        return
    driver_error = ctx.original_exception
    sqlstate = getattr(driver_error, "sqlstate", None)
    exc_type = _BY_SQLSTATE.get(sqlstate)
    if exc_type is None:
        is_data = str(sqlstate).startswith(_DATA_EXCEPTION_CLASS)
        exc_type = DataViolationError if is_data else DatabaseException
    raise exc_type(str(driver_error)) from driver_error
