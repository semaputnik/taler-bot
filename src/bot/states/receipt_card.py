from aiogram.fsm.state import State, StatesGroup


class ReceiptCardSG(StatesGroup):
    main = State()
    items = State()
    item = State()
    photo = State()
    issue = State()
    issue_input = State()
    review_done = State()
    delete_confirm = State()
