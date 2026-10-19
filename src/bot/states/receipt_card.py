from aiogram.fsm.state import State, StatesGroup


class ReceiptCardSG(StatesGroup):
    main = State()
    items = State()
    item = State()
    item_input = State()
    item_category = State()
    category = State()
    tags = State()
    photo = State()
    issue = State()
    issue_input = State()
    issue_rename = State()
    review_done = State()
    edit = State()
    edit_input = State()
    delete_confirm = State()
    reparse_confirm = State()
