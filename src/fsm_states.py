from aiogram.fsm.state import State, StatesGroup


class StartFsm(StatesGroup):
    put_fullname = State()
    put_group = State()
