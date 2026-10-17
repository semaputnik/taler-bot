class AppException(Exception):
    """Root of the application's exception hierarchy."""


class DatabaseException(AppException):
    """A database failure that services may need to react to."""


class UniqueViolationError(DatabaseException):
    pass


class ForeignKeyViolationError(DatabaseException):
    pass


class CheckViolationError(DatabaseException):
    pass


class DataViolationError(DatabaseException):
    """A value does not fit its column (too long, out of range, malformed)."""


class DomainException(AppException):
    """A receipt rule was violated; raised by the aggregates, never by the database."""


class InvalidReceiptTransition(DomainException):
    """The receipt's status does not allow this action (for example parsing a duplicate receipt)."""


class DuplicatePhoto(DomainException):
    """The user already sent a photo with this Telegram unique id."""


class UnknownIssue(DomainException):
    """The issue is not an active issue of the receipt."""


class InvalidIssueResolution(DomainException):
    """An issue can only be resolved as confirmed, corrected or skipped."""


class InvalidEdit(DomainException):
    """An edit names a field that cannot be edited, or carries a value of the wrong kind."""


class InvalidReceiptData(DomainException):
    """A value breaks a model invariant (for example a naive datetime)."""


class UnknownStore(DomainException):
    """The catalog has no store with this key."""


class UnknownProduct(DomainException):
    """The catalog has no product with this key."""


class ReceiptNotFound(AppException):
    """No receipt with this id belongs to the user (another user's receipt counts as missing)."""


class UserNotFound(AppException):
    """No user with this id."""


class IntegrationException(AppException):
    """An external system (LLM, storage, ...) failed."""
