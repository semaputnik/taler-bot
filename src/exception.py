class AppException(Exception):
    """Root of the application's exception hierarchy."""


class DatabaseException(AppException):
    """A database failure that use cases may need to react to."""


class UniqueViolationError(DatabaseException):
    pass


class ForeignKeyViolationError(DatabaseException):
    pass


class CheckViolationError(DatabaseException):
    pass


class DataViolationError(DatabaseException):
    """A value does not fit its column (too long, out of range, malformed)."""


class IntegrationException(AppException):
    """An external system (LLM, storage, ...) failed."""
