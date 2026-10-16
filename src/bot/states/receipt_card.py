from aiogram.fsm.state import State, StatesGroup


class ReceiptCardSG(StatesGroup):
    main = State()
    items = State()
    item = State()
    delete_confirm = State()
