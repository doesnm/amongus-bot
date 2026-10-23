import structlog
from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from fsm_states import StartFsm
from src.filters import IsRegistered

participant_router = Router()
logger = structlog.get_logger(__name__)


@participant_router.message(CommandStart(), IsRegistered())
async def start_message(message: Message, state: FSMContext, session: AsyncSession):
    await message.answer("Я ЖИВОЙ")


@participant_router.message(Command("target"))
async def target_handler(message: Message, session: AsyncSession):
    pass  # тут таргет текущего пользвателя.


@participant_router.message(Command("kill"))
async def kill_handler(message: Message, db):
    pass


@participant_router.message(Command("me"))
async def profile_handler(message: Message):
    pass


@participant_router.message(Command("rules"))
async def rules_handler(message: Message):
    pass
