from html import escape

import structlog
from aiogram import Bot, Router, F
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import (
    CallbackQuery,
    ForceReply,
    Message,
    InlineQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from sqlalchemy.ext.asyncio import AsyncSession
from aiogram.exceptions import TelegramAPIError
from sqlmodel import select, func, col

from filters import IsOrganizer
from src import chain
from src.config import get_config
from src.fsm_states import KillFsm, StartFsm
from src.filters import IsRegistered
from src.models import (
    GameAndUsers,
    GameState,
    GameStatus,
    KillCase,
    KillCaseStatus,
    PermissionKey,
    UserState,
    UserVictim,
)
from src.utils import (
    notify_new_form,
    NewFormCallbackData,
    NewFormTypes,
    describe,
    KillVictimCallbackData,
    KillVictimAnswer,
    edit_org_report,
    kill_report_text,
    kill_review_keyboard,
    kill_victim_keyboard,
)

participant_router = Router()
logger = structlog.get_logger(__name__)


@participant_router.message(CommandStart())
async def start_message(message: Message, state: FSMContext, session: AsyncSession):

    if message.from_user:
        user_id = message.from_user.id

        existing = await session.get(UserState, user_id)
        if existing is None or existing.form_accepted is False:
            if message.chat.type != ChatType.PRIVATE:
                return await message.answer(
                    "Отправьте в ЛС для регистрации вашей фур персоны"
                )
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
        tg_name = tg_user.username if tg_user.username else "username нет"

        # отклонённый пользователь остаётся в БД, поэтому повторная заявка обновляет его запись
        user = await session.get(UserState, tg_user.id)
        if user is None:
            user = UserState(
                tg_id=tg_user.id,
                permission_key=PermissionKey.user,
                tg_name=tg_name,
                killed=False,
                full_name=data["fullname"],
                group=data["group"],
                form_accepted=None,
            )
        elif user.form_accepted is False:
            user.tg_name = tg_name
            user.full_name = data["fullname"]
            user.group = data["group"]
            user.form_accepted = None
            user.reject_reason = None
        else:
            await state.clear()
            return await message.answer("Ваша заявка уже подана")

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


@participant_router.callback_query(NewFormCallbackData.filter())
async def new_form_handler(cb: CallbackQuery, session: AsyncSession):
    user = await session.get(UserState, cb.from_user.id)
    if user is None:
        await cb.answer("Вы не зарегистрированы")
        return
    if user.permission_key != PermissionKey.organizer:
        await cb.answer("Вы не являетесь оргнизатором")
        return

    data = NewFormCallbackData.unpack(cb.data)

    user = await session.get(UserState, data.user_id)
    if user is None or user.form_accepted is not None:
        await cb.message.edit_reply_markup(reply_markup=None)
        await cb.answer("Эта заявка уже рассмотрена", show_alert=True)
        return

    reviewer = escape(cb.from_user.full_name)
    if data.answer_type == NewFormTypes.deny:
        await cb.bot.send_message(data.user_id, "Ваша заявка была отклонена")

        user.form_accepted = False
        verdict = f"Отклонён ({reviewer})"
    else:
        await cb.bot.send_message(
            data.user_id, "Ваше участие было принято в текущую игру, ожидайте"
        )
        user.form_accepted = True
        user.permission_key = PermissionKey.participant
        session.add(
            GameAndUsers(
                user_id=user.tg_id, game_id=(await GameState.current_game(session)).id
            )
        )
        verdict = f"Принят ({reviewer})"

    session.add(user)
    await cb.message.edit_text(
        f"{cb.message.html_text}\n\n{verdict}", parse_mode="HTML", reply_markup=None
    )
    await cb.answer()


@participant_router.message(Command("target"), IsRegistered())
async def target_handler(message: Message, session: AsyncSession):
    if message.from_user:
        target = await chain.get_target(session, message.from_user.id)
        if target is None:
            await message.answer("У тебя сейчас нет жертвы")
            return
        await message.answer(f"Твоя жертва: {target.full_name}")


@participant_router.message(Command("kill"), IsRegistered())
async def kill_handler(message: Message, session: AsyncSession, state: FSMContext):
    game = await GameState.current_game(session)
    if game is None or game.status != GameStatus.GameIsGoing:
        return await message.answer("Игра сейчас не идёт")

    user = await session.get(UserState, message.from_user.id)
    if user.permission_key != PermissionKey.participant or user.killed:
        return await message.answer("Ты не участвуешь в игре или уже выбыл")

    pending = await session.scalar(
        select(KillCase.id).where(
            KillCase.from_user_id == user.tg_id,
            col(KillCase.status).in_((KillCaseStatus.disputed,)),
        )
    )
    if pending is not None:
        return await message.answer(
            "У тебя уже есть отчёт на пере расмотрении, дождись решения организаторов"
        )

    target = await chain.get_target(session, user.tg_id)
    if target is None:
        return await message.answer("У тебя сейчас нет жертвы")

    await state.set_state(KillFsm.wait_evidence)
    await message.answer(
        f"Твоя жертва: {target.full_name}\n"
        "Пришли совместное фото или кружок с ней. Любое другое сообщение отменит отчёт."
    )


@participant_router.callback_query(KillVictimCallbackData.filter())
async def kill_victim_handler(
    callback: CallbackQuery,
    callback_data: KillVictimCallbackData,
    session: AsyncSession,
    bot: Bot,
):
    case = await session.get(KillCase, callback_data.case_id)
    link = await session.get(UserVictim, case.user_victim_id) if case else None
    if link is None or link.victim_id != callback.from_user.id:
        return await callback.answer("Отчёт не найден", show_alert=True)

    await callback.message.edit_reply_markup(reply_markup=None)
    if case.status != KillCaseStatus.pending:
        return await callback.answer(
            "По этому отчёту уже есть решение", show_alert=True
        )

    hunter = await session.get(UserState, case.from_user_id)
    victim = await session.get(UserState, link.victim_id)

    if callback_data.answer == KillVictimAnswer.dispute:
        case.status = KillCaseStatus.disputed
        victim_text = "Ты оспорил убийство. Организаторы рассмотрят отчёт"
        org_note = "Жертва ОСПОРИЛА убийство"
    else:
        victim_text = "Ты подтвердил убийство. Ждём решения организаторов"
        org_note = "Жертва подтвердила убийство"

    await callback.message.edit_text(victim_text)
    await edit_org_report(
        bot,
        case,
        f"{kill_report_text(hunter, victim, case)}\n\n{org_note}",
        reply_markup=kill_review_keyboard(case.id),
    )
    await callback.answer()


@participant_router.message(Command("me"), IsRegistered())
async def profile_handler(message: Message, session: AsyncSession):
    user = await session.get(UserState, message.from_user.id)
    kills = await session.scalar(
        select(func.count())
        .select_from(KillCase)
        .where(
            KillCase.status == KillCaseStatus.approved,
            KillCase.from_user_id == user.tg_id,
        )
    )
    victim = await chain.get_target(session, user.tg_id)
    victim_name = (
        f"{victim.tg_name}, ФИО: {victim.full_name}, Группа: {victim.group}" if victim else None
    )

    await message.answer(
        f"{user.full_name}, {user.group}\n"
        f"Статус: {'выбыл' if user.killed else 'жив'}\n"
        f"Убийств: {kills}\n"
        f"Текущяя цель: {victim_name if victim_name else 'Вашей цели нету'}"
    )


rules_global = "Это игра цепочки."


@participant_router.message(Command("rules"))
async def rules_handler(message: Message):
    await message.answer(rules_global)


# Хендлеры состояния стоят в конце, чтобы команды выше срабатывали раньше них
@participant_router.message(KillFsm.wait_evidence, F.photo | F.video_note)
async def kill_evidence_handler(
    message: Message, session: AsyncSession, state: FSMContext, bot: Bot
):
    await state.clear()

    link = await chain.get_link_by_hunter(session, message.from_user.id)
    if link is None:
        return await message.answer("У тебя сейчас цели")

    hunter = await session.get(UserState, link.user_id)
    victim = await session.get(UserState, link.victim_id)
    case = KillCase(
        from_user_id=hunter.tg_id,
        evidence_id=message.photo[-1].file_id
        if message.photo
        else message.video_note.file_id,
        user_victim_id=link.id,
        approved_at=None,
    )
    session.add(case)

    text = kill_report_text(hunter, victim, case)
    org_chat_id = get_config().org_chat_id
    if message.photo:
        report = await bot.send_photo(
            org_chat_id,
            case.evidence_id,
            caption=text,
            reply_markup=kill_review_keyboard(case.id),
        )
    else:
        await bot.send_video_note(org_chat_id, case.evidence_id)
        report = await bot.send_message(
            org_chat_id, text, reply_markup=kill_review_keyboard(case.id)
        )
    case.org_message_id = report.message_id
    case.org_message_is_photo = bool(message.photo)

    try:
        question = await bot.send_message(
            victim.tg_id,
            f"{hunter.full_name} сообщает что жесточайшим методом убил тебя. Это правда?",
            reply_markup=kill_victim_keyboard(case.id),
        )
        case.victim_message_id = question.message_id
    except TelegramAPIError:
        logger.warning("Failed to notify victim", user_id=victim.tg_id, exc_info=True)

    await message.answer("Отчёт отправлен организаторам жди решения")


@participant_router.message(KillFsm.wait_evidence)
async def kill_cancel_handler(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Нужно было фото или кружок. Отчёт отменён, начни заново с /kill"
    )
