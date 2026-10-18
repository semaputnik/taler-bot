from aiogram.fsm.state import State, StatesGroup


class ExpenseCardSG(StatesGroup):
    main = State()
    amount = State()
    payee = State()
    payee_name = State()
    source = State()
    new_card = State()
    source_rename = State()
    category = State()
    date = State()
    date_text = State()
    tags = State()
    delete_confirm = State()
