from aiogram.fsm.state import State, StatesGroup


class ExpenseEntrySG(StatesGroup):
    payee = State()
    payee_name = State()
    source = State()
    new_card = State()
    category = State()
    date = State()
    date_text = State()
    tags = State()
