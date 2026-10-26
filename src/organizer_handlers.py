import asyncio
import datetime

import structlog
from aiogram import Bot, Router, session
from aiogram.filters import Command, CommandObject, command
from aiogram.types import Message
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import Session, select

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
    game = (await session.scalars(select(GameState))).first()
    if game is None:
        game = GameState()
        session.add(game)
    if game.status != GameStatus.InvitationsPending:
        await message.answer("Игра уже запущена или завершена")
        return

    stmt = select(UserState).where(
        UserState.permission_key == PermissionKey.participant,
        UserState.killed == False,  # noqa: E712
        UserState.form_accepted == True,
    )
    players = list(await session.scalars(stmt))

    try:
        links = await chain.build_chain(session, [p.tg_id for p in players])
    except chain.ChainError as e:
        await message.answer(str(e))
        return

    game.status = GameStatus.GameIsGoing
    game.started_at = datetime.datetime.now(datetime.UTC)

    names = {p.tg_id: p.full_name for p in players}
    for link in links:
        await notify(
            bot, link.user_id, f"Игра началась! Твоя жертва: {names[link.victim_id]}"
        )

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


@org_router.message(Command("stats"))
async def game_stats(message: Message):
    pass


@org_router.message(Command("export"))
async def export(message: Message, session: Session):
    pass


@org_router.message(Command("broadcast"))
async def broadcast(
    message: Message, command: CommandObject, session: Session, bot: Bot
):
    text = command.args

    if not text:
        message.answer("Использовать так: /broadcast <текст>")
        return

    user_ids = session.exec(select(UserState.tg_id)).all()

    msg = await message.answer("Сообщение отправляется...")

    for user_id in user_ids:
        try:
            await notify(bot, user_id, text)
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
            await notify(bot, user_id, text)
        await asyncio.sleep(0.05)

    msg.edit_text("Сообщение отправленно!")


@org_router.message(Command("end_game"))
async def end_game(message: Message):
    pass
