import pytest
from sqlalchemy.exc import IntegrityError

from src.database.errors import translate_db_errors
from src.exception import (
    CheckViolationError,
    DatabaseException,
    ForeignKeyViolationError,
    UniqueViolationError,
)


class FakeDriverError(Exception):
    def __init__(self, sqlstate: str) -> None:
        super().__init__(sqlstate)
        self.sqlstate = sqlstate


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
        with translate_db_errors():
            raise IntegrityError("stmt", {}, FakeDriverError(sqlstate))
    assert isinstance(caught.value, DatabaseException)
    assert not isinstance(caught.value, IntegrityError)


async def test_real_unique_violation_is_translated(session):
    from src.database.models import User

    session.add_all([User(id=1), User(id=1)])
    with pytest.raises(UniqueViolationError):
        with translate_db_errors():
            await session.flush()
