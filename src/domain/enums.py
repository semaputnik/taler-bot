from enum import StrEnum


class ReceiptStatus(StrEnum):
    PENDING = "pending"
    PARSING = "parsing"
    PARSED = "parsed"
    FAILED = "failed"
    NOT_RECEIPT = "not_receipt"
    # Parsed alone, looks like a known receipt but the key differs; waiting for the user.
    AWAITING_MATCH = "awaiting_match"
    # Turned out to be another photo of `merged_into_id`; its photo and parse moved there.
    MERGED = "merged"


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
    # Photos of one receipt disagree, or a re-parse disagrees with a user edit.
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
