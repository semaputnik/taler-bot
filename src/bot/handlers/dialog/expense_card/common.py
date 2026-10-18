class DialogDataKeys:
    EXPENSE_ID = "expense_id"
    INPUT_ERROR = "input_error"  # the last typed value was refused; cleared on entry and on Back


class PreviewDataKeys:
    TEXT = "text"
    CAN_EDIT = "can_edit"  # the expense exists and is not deleted: the card has buttons
    CAN_RENAME = "can_rename"  # the expense is paid with a card (not cash, not nothing)
