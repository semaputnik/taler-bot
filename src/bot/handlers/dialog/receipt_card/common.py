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
    INPUT_ERROR = "input_error"  # the last typed value was refused; cleared on entry and on Back


class PreviewDataKeys:
    TEXT = "text"
    CAN_DELETE = "can_delete"
    HAS_ITEMS = "has_items"
    ITEMS = "items"
    PHOTO = "photo"
    REVIEW_COUNT = "review_count"
    HAS_ISSUE = "has_issue"
    CAN_ENTER_VALUE = "can_enter_value"
    REVIEWED = "reviewed"
