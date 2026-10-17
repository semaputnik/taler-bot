class DialogDataKeys:
    RECEIPT_ID = "receipt_id"
    ITEM_REF = "item_ref"
    # The review walk, loaded once when it is entered.
    WALK = "walk"  # the issue ids in walk order
    POSITION = "position"  # index into WALK of the issue on screen
    CURRENT_ISSUE_ID = "current_issue_id"  # WALK[POSITION], kept in step by `settle`
    CONFIRMED = "confirmed"
    CORRECTED = "corrected"
    SKIPPED = "skipped"
    EDIT_FIELD = "edit_field"  # the item field being edited: name, quantity, unit_price, line_total
    PRODUCT_KEY = "product_key"  # the catalog product behind the selected item
    INPUT_ERROR = "input_error"  # the last typed value was refused; cleared on entry and on Back


class PreviewDataKeys:
    TEXT = "text"
    CAN_DELETE = "can_delete"
    HAS_ITEMS = "has_items"
    CAN_REPARSE = "can_reparse"
    ITEMS = "items"
    PHOTO = "photo"
    REVIEW_COUNT = "review_count"
    HAS_ISSUE = "has_issue"
    CAN_ENTER_VALUE = "can_enter_value"
    CAN_RENAME = "can_rename"
    REVIEWED = "reviewed"
    HAS_ITEM = "has_item"
    HAS_EXPENSE = "has_expense"
    CATEGORIES = "categories"


# The categories offered for a product, in the order of the list. The service refuses any
# other string; `tests/bot/test_item_edit.py` keeps this list equal to the domain's.
CATEGORIES = (
    "produce",
    "meat",
    "fish",
    "dairy",
    "bakery",
    "drinks",
    "alcohol",
    "snacks",
    "frozen",
    "pantry",
    "household",
    "personal_care",
    "baby",
    "pet",
    "other",
)


# The categories offered for a receipt's expense, in the order of the list. The service refuses
# any other string; `tests/bot/test_expense_category.py` keeps this list equal to the domain's.
EXPENSE_CATEGORIES = (
    "groceries",
    "restaurants",
    "transport",
    "rent",
    "utilities",
    "health",
    "entertainment",
    "subscriptions",
    "clothing",
    "travel",
    "gifts",
    "other",
)
