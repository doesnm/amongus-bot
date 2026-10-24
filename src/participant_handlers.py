import structlog
from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from src import chain
from src.fsm_states import StartFsm
from src.filters import IsRegistered

participant_router = Router()
logger = structlog.get_logger(__name__)


@participant_router.message(CommandStart(), IsRegistered())
async def start_message(message: Message, state: FSMContext, session: AsyncSession):
    await message.answer("Я ЖИВОЙ")


@participant_router.message(Command("target"), IsRegistered())
async def target_handler(message: Message, session: AsyncSession):
    target = await chain.get_target(session, message.from_user.id)
    if target is None:
        await message.answer("У тебя сейчас нет жертвы")
        return
    await message.answer(f"Твоя жертва: {target.full_name}")


@participant_router.message(Command("kill"))
async def kill_handler(message: Message, db):
    pass


@participant_router.message(Command("me"))
async def profile_handler(message: Message):
    pass


@participant_router.message(Command("rules"))
async def rules_handler(message: Message):
    pass
