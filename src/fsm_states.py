

from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State


class StartFsmContext(FSMContext):
    put_group = State()

