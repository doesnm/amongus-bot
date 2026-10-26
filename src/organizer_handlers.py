import asyncio
import datetime

import structlog
from aiogram import Bot, Router, F
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, func

from src.models import KillCase, KillCaseStatus
from src import chain
from src.filters import IsOrganizer
from src.models import GameState, GameStatus, PermissionKey, UserState

org_router = Router(name="org_router")
org_router.message.filter(IsOrganizer())
logger = structlog.get_logger(__name__)


async def notify(bot: Bot, user_id: int, text: str) -> None:
    try:
        await bot.send_message(user_id, text)
    except Exception:
        logger.warning("Failed to notify user", user_id=user_id, exc_info=True)


async def notify_relink(bot: Bot, session: AsyncSession, relink: chain.Relink) -> None:
    if relink.hunter_id is None:
        return
    if relink.new_target_id is None:
        await notify(bot, relink.hunter_id, "Ты остался последним живым игроком!")
        return
    target = await session.get(UserState, relink.new_target_id)
    await notify(bot, relink.hunter_id, f"Твоя новая жертва: {target.full_name}")


@org_router.message(Command("start_game"))
async def start_game(message: Message, session: AsyncSession, bot: Bot):
    game = await GameState.current_game(session)
    if game is None or game.status != GameStatus.InvitationsPending:
        await message.answer("Игра уже запущена или завершена")
        return

    stmt = select(UserState).where(
        UserState.permission_key == PermissionKey.participant,
        UserState.killed == False,  # noqa: E712
        UserState.form_accepted == True,
    )
    players = list(await session.scalars(stmt))

    try:
        links = await chain.build_chain(session, [p.tg_id for p in players], game_id=game.id)
    except chain.ChainError as e:
        await message.answer(str(e))
        return

    game.status = GameStatus.GameIsGoing
    game.started_at = datetime.datetime.now(datetime.UTC)

    names = {p.tg_id: p.full_name for p in players}
    for link in links:
        await notify(bot, link.user_id, f"Игра началась! Твоя жертва: {names[link.victim_id]}")

    await message.answer(f"Игра запущена, участников: {len(players)}")


@org_router.message(Command("kick"))
async def kick_participant(
    message: Message, command: CommandObject, session: AsyncSession, bot: Bot
):
    if not command.args or not command.args.strip().isdigit():
        await message.answer("Использование: /kick <tg_id>")
        return
    user_id = int(command.args.strip())

    try:
        relink = await chain.remove_from_chain(session, user_id)
    except chain.ChainError as e:
        await message.answer(str(e))
        return

    await notify(bot, user_id, "Ты исключён из игры организаторами")
    await notify_relink(bot, session, relink)
    await message.answer(f"Игрок {user_id} исключён, цепочка восстановлена")


@org_router.message(Command("game_stats"))
async def game_stats(message: Message, session: AsyncSession):
    game = (await session.scalars(
        select(GameState).where(GameState.status != GameStatus.Finalized)
    )).first()
    if game is None:
        await message.answer("Активной игры нет")
        return

    players = list(await session.scalars(select(UserState).where(
        UserState.permission_key == PermissionKey.participant,
        UserState.form_accepted == True,
    )))
    alive = sum(not p.killed for p in players)

    kills_by_status = dict((await session.execute(
        select(KillCase.status, func.count()).group_by(KillCase.status)
    )).all())

    top = (await session.execute(
        select(UserState.full_name, func.count(KillCase.id).label("kills"))
        .join(KillCase, KillCase.from_user_id == UserState.tg_id)
        .where(KillCase.status == KillCaseStatus.approved)
        .group_by(UserState.full_name)
        .order_by(func.count(KillCase.id).desc())
        .limit(5)
    )).all()

    lines = [
        f"Игра: {game.game_name} ({game.status.value})",
        f"Начата: {game.started_at}" if game.started_at else "Ещё не начата",
        f"Участников: {len(players)}, живых: {alive}, выбыло: {len(players) - alive}",
        f"Убийств подтверждено: {kills_by_status.get(KillCaseStatus.approved, 0)}, "
        f"на проверке: {kills_by_status.get(KillCaseStatus.pending, 0)}, "
        f"оспорено: {kills_by_status.get(KillCaseStatus.disputed, 0)}",
    ]
    if top:
        lines.append("\nТоп убийц:")
        lines += [f"{i}. {name} - {kills}" for i, (name, kills) in enumerate(top, 1)]

    await message.answer("\n".join(lines))


@org_router.message(Command("export"))
async def export(message: Message):
    pass


@org_router.message(Command("broadcast"))
@org_router.message(Command("broadcast"))
async def broadcast(
    message: Message, command: CommandObject, session: AsyncSession, bot: Bot
):
    text = command.args

    if not text:
        await message.answer("Использовать так: /broadcast <текст>")
        return

    user_ids = (await session.scalars(select(UserState.tg_id))).all()

    msg = await message.answer("Сообщение отправляется...")

    for user_id in user_ids:
        try:
            await notify(bot, user_id, text)
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
            await notify(bot, user_id, text)
        await asyncio.sleep(0.05)

    await msg.edit_text("Сообщение отправленно!")


class AcceptState(StatesGroup):
    wait_to_prompt = State()


@org_router.message(Command("end_game"), IsOrganizer())
async def end_game(message: Message, session: AsyncSession, state: FSMContext):
    if not await GameState.current_game(session):
        return await message.answer("Текущая игра не идет")

    await message.answer("Вы уверены что хотите закончить текущую игру? [Да/Нет]")

    await state.set_state(AcceptState.wait_to_prompt)


@org_router.message(AcceptState.wait_to_prompt)
async def waiting_for_answer(message: Message, session: AsyncSession, state: FSMContext):
    await state.clear()
    if message.text not in ("Да", "Д", "Y"):
        return await message.answer("Отмена закрытие текущей игры")

    await message.answer("Игра была закончена, всем участникам была отправлена их стаистика, новая игра в ожидании")

    game = await GameState.close_the_game(session)

    query = select(UserState).where(UserState.games.any(id=game.id))
    users = (await session.scalars(query)).all()

    for user in users:
        killed_count = await session.scalar(select(func.count()).select_from(KillCase).where(
            KillCase.status == KillCaseStatus.approved, KillCase.from_user_id == user.tg_id
        ))
        text = (
            f"Игра была закончена. вы убили {killed_count} человек потверждено, ГГ ВП"
        )

        try:
            await message.bot.send_message(user.tg_id, text)
        except TelegramAPIError:
            logger.info(f"Telegram user blocked this bot: {user.tg_id}")

    new_game = GameState(
        status=GameStatus.InvitationsPending,
        game_name="Цепочка убийств",
        playing_users=[],
    )

    session.add(new_game)

    await message.answer("ГГ ВП")

    return


