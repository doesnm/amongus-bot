from html import escape

import structlog
from aiogram import Bot, Router, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, ForceReply, Message, InlineQuery
from sqlalchemy.ext.asyncio import AsyncSession

from src import chain
from src.config import get_config
from src.fsm_states import StartFsm
from src.filters import IsRegistered
from src.models import PermissionKey, UserState
from src.utils import notify_new_form, NewFormCallbackData, NewFormTypes

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


@participant_router.message(StartFsm.put_group, F.text)
async def enter_group(message: Message, state: FSMContext, session: AsyncSession):
    text = message.text.strip()

    if len(text.split("=")) != 2 and len(text.split("-")) != 2:
        await message.answer("Неправильно написанная группа")
        await state.clear()
        return

    data = await state.update_data(group=message.text)

    tg_user = message.from_user

    if tg_user:
        user = UserState(
            tg_id=tg_user.id,
            permission_key=PermissionKey.user,
            tg_name=tg_user.username if tg_user.username else "username нет",
            killed=False,
            full_name=data["fullname"],
            group=data["group"],
            form_accepted=None,
        )

        session.add(user)

        await message.answer("Ваша форма к регистрации на ожидании у организаторов")
        await notify_new_form(message.bot, user)

        await state.clear()


@participant_router.message(StartFsm.put_fullname, F.text)
async def enter_fullname(message: Message, state: FSMContext):
    text = message.text.strip()

    if not len(text.split()) in {2, 3}:
        await message.answer("Вы неправильно написали свое ФИО")
        await state.clear()
        return

    await state.update_data(fullname=message.text)
    await state.set_state(StartFsm.put_group)
    await message.answer("Напиши свою группу (например SE-2614):")


@participant_router.inline_query(F.query.startswith("new_form"))
async def new_form_handler(inline_query: InlineQuery, session: AsyncSession):
    data = NewFormCallbackData.unpack(inline_query.query)

    user = await session.get(UserState, data.user_id)
    if data.answer_type == NewFormTypes.deny:
        await inline_query.bot.send_message(data.user_id, "Ваша заявка была отклонена")

        user.form_accepted = False

    else:
        await inline_query.bot.send_message(data.user_id, "Ваше участие было принято в текущую игру, ожидайте")
        user.form_accepted = True


    session.add(user)


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
