from multiprocessing.managers import State

from aiogram.fsm.context import FSMContext


class StartFsmContext(FSMContext):
    put_group = State()

