from enum import StrEnum


class ReceiptStatus(StrEnum):
    PENDING = "pending"
    PARSING = "parsing"
    PARSED = "parsed"
    FAILED = "failed"
    NOT_RECEIPT = "not_receipt"
    # Same receipt key as an earlier parsed receipt, `duplicate_of_id`.
    DUPLICATE = "duplicate"


class ParseStatus(StrEnum):
    OK = "ok"
    FAILED = "failed"


class Category(StrEnum):
    PRODUCE = "produce"
    MEAT = "meat"
    FISH = "fish"
    DAIRY = "dairy"
    BAKERY = "bakery"
    DRINKS = "drinks"
    ALCOHOL = "alcohol"
    SNACKS = "snacks"
    FROZEN = "frozen"
    PANTRY = "pantry"
    HOUSEHOLD = "household"
    PERSONAL_CARE = "personal_care"
    BABY = "baby"
    PET = "pet"
    OTHER = "other"


class IssueSource(StrEnum):
    MODEL = "model"
    WORKFLOW = "workflow"
    # A re-parse disagrees with a user edit (the value "merge" is kept for stored rows).
    MERGE = "merge"


class IssueSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class IssueResolution(StrEnum):
    OPEN = "open"
    CONFIRMED = "confirmed"
    CORRECTED = "corrected"
    SKIPPED = "skipped"


class EditTarget(StrEnum):
    RECEIPT = "receipt"
    ITEM = "item"
