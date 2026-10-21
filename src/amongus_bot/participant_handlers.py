import structlog
from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

participant_router = Router()
logger = structlog.get_logger(__name__)


@participant_router.message(Command("start"))
async def start_message(message: Message, fsm_context: FSMContext):
    pass


@participant_router.message(Command("target"))
async def target_handler(message: Message, db):
    pass # тут таргет текущего пользвателя.

@participant_router.message(Command("kill"))
async def kill_handler(message: Message, db):
    pass

@participant_router.message(Command("me"))
async def profile_handler(message: Message):
    pass


@participant_router.message(Command("rules"))
async def rules_handler(message: Message):
    pass