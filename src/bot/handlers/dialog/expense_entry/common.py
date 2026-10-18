class DialogDataKeys:
    AMOUNT = "amount"  # the typed amount, as text ("12.50"); a Decimal does not survive the FSM
    PAYEE_KEY = "payee_key"  # a recent payee that was picked ...
    PAYEE_NAME = "payee_name"  # ... or a name that was typed; at most one is set
    SOURCE = "source"  # a card's id as text, or `pickers.CASH_ID` ...
    NEW_CARD = "new_card"  # ... or the name of a card to create; at most one is set
    CATEGORY = "category"
    SPENT_AT = "spent_at"  # the day, as an ISO date
    INPUT_ERROR = "input_error"  # the last typed value was refused; cleared on entry and on Back


class PreviewDataKeys:
    TEXT = "text"
