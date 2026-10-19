class TransferKeys:
    """Keys passed between dialogs, and from handlers into a dialog, through `start_data`."""

    RECEIPT_ID = "receipt_id"
    AMOUNT = "amount"
    EXPENSE_ID = "expense_id"
    # True on a card the user asked for (a history row, a copy of an older card): its Close
    # deletes the message instead of only hiding the buttons.
    DISMISSIBLE = "dismissible"
