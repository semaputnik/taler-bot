from aiogram.fsm.state import State, StatesGroup


class ReceiptCardSG(StatesGroup):
    main = State()
    items = State()
    item = State()
    item_input = State()
    item_category = State()
    photo = State()
    issue = State()
    issue_input = State()
    review_done = State()
    delete_confirm = State()
