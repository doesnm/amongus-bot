from aiogram.fsm.state import State, StatesGroup


class StartFsm(StatesGroup):
    put_group = State()

