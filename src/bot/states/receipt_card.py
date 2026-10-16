from aiogram.fsm.state import State, StatesGroup


class ReceiptCardSG(StatesGroup):
    main = State()
    delete_confirm = State()
