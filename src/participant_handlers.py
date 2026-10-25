from os import name

from sqlmodel import Session
import structlog
from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from src import chain
from src.fsm_states import StartFsm
from src.filters import IsRegistered
from src.models import PermissionKey, UserState

participant_router = Router()
logger = structlog.get_logger(__name__)


@participant_router.message(CommandStart())
async def start_message(message: Message, state: FSMContext, session: AsyncSession):
    if message.from_user:
        user_id = message.from_user.id

        if not await session.get(UserState, user_id):
            await state.clear()
            await message.answer("Привет! Напиши своё полное имя: ")
            await state.set_state(StartFsm.put_fullname)
        else:
            await message.answer("привет")


@participant_router.message(StartFsm.put_fullname)
async def enter_fullname(message: Message, state: FSMContext):
    await state.update_data(fullname=message.text)
    await state.set_state(StartFsm.put_group)
    await message.answer("Напиши свою группу (например SE-2614):")


@participant_router.message(StartFsm.put_group)
async def enter_group(message: Message, state: FSMContext, session: Session):
    data = await state.update_data(group=message.text)
    await state.clear()

    tg_user = message.from_user

    if tg_user:
        user = UserState(
            tg_id=tg_user.id,
            permission_key=PermissionKey.user,
            tg_name=tg_user.username if tg_user.username else "username нет",
            killed=False,
            full_name=data["fullname"],
            group=data["group"],
        )

        session.add(user)

        await message.answer("Регистрация завершена!")


@participant_router.message(Command("target"), IsRegistered())
async def target_handler(message: Message, session: AsyncSession):
    if message.from_user:
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
