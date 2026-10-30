import asyncio
import csv
import datetime
import html
import io
from collections import Counter
from enum import Enum

import structlog
from aiogram import Bot, Router, F
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.filters import Command, CommandObject
from aiogram.filters.callback_data import CallbackData
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select, func

from src.models import GameAndUsers, KillCase, KillCaseStatus, UserVictim
from src import chain
from src.filters import IsOrganizer
from src.models import GameState, GameStatus, PermissionKey, UserState
from src.utils import (
    KillReviewAction,
    KillReviewCallbackData,
    describe,
    edit_org_report,
    edit_victim_question,
    kill_report_text,
)

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
        links = await chain.build_chain(
            session, [p.tg_id for p in players], game_id=game.id
        )
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


@org_router.callback_query(KillReviewCallbackData.filter(), IsOrganizer())
async def kill_review(
    callback: CallbackQuery,
    callback_data: KillReviewCallbackData,
    session: AsyncSession,
    bot: Bot,
):
    case = await session.get(KillCase, callback_data.case_id)
    await callback.message.edit_reply_markup(reply_markup=None)
    if case is None or case.status not in (
        KillCaseStatus.pending,
        KillCaseStatus.disputed,
    ):
        return await callback.answer("Этот отчёт уже рассмотрен", show_alert=True)

    link = await session.get(UserVictim, case.user_victim_id)
    hunter = await session.get(UserState, case.from_user_id)
    victim = await session.get(UserState, link.victim_id)
    report = kill_report_text(hunter, victim, case)
    reviewer = callback.from_user.full_name

    if callback_data.action == KillReviewAction.reject:
        case.status = KillCaseStatus.rejected
        await notify(
            bot, case.from_user_id, "Твой отчёт об убийстве отклонён организаторами"
        )
        await edit_victim_question(
            bot, case, victim.tg_id, "Организаторы отклонили отчёт об убийстве"
        )
        await edit_org_report(bot, case, f"{report}\n\nОтклонено ({reviewer})")
        return await callback.answer()

    try:
        relink = await chain.apply_kill(session, case.user_victim_id)
    except chain.ChainError as e:
        case.status = KillCaseStatus.rejected
        await notify(bot, case.from_user_id, f"Твой отчёт отклонён: {e}")
        await edit_victim_question(
            bot, case, victim.tg_id, "Отчёт об убийстве отклонён: цепочка изменилась"
        )
        await edit_org_report(bot, case, f"{report}\n\nНе засчитано: {e}")
        return await callback.answer()

    case.status = KillCaseStatus.approved
    case.approved_at = datetime.datetime.now(datetime.UTC)
    victim_text = "Организаторы засчитали твоё убийство. Ты выбываешь из игры"
    if not await edit_victim_question(bot, case, victim.tg_id, victim_text):
        await notify(bot, victim.tg_id, victim_text)
    await notify(bot, case.from_user_id, "Убийство засчитано!")
    await notify_relink(bot, session, relink)
    await edit_org_report(bot, case, f"{report}\n\nПринято ({reviewer})")

    if relink.new_target_id is None:
        game = await GameState.close_the_game(session)
        game.forced_ending = False
        await GameState.start_next_game(session, "Цепочка убийств")
        winner = await session.get(UserState, relink.hunter_id)
        await callback.message.answer(
            f"Остался один игрок: {describe(winner)}\n"
            "Игра завершена автоматически, новая игра ждёт регистрации"
        )
    await callback.answer()


@org_router.message(Command("game_stats"))
async def game_stats(message: Message, session: AsyncSession):
    game = (
        await session.scalars(
            select(GameState).where(GameState.status != GameStatus.Finalized)
        )
    ).first()
    if game is None:
        await message.answer("Активной игры нет")
        return

    players = list(
        await session.scalars(
            select(UserState).where(
                UserState.permission_key == PermissionKey.participant,
                UserState.form_accepted == True,
            )
        )
    )
    alive = sum(not p.killed for p in players)

    kills_by_status = dict(
        (
            await session.execute(
                select(KillCase.status, func.count()).group_by(KillCase.status)
            )
        ).all()
    )

    top = (
        await session.execute(
            select(UserState.full_name, func.count(KillCase.id).label("kills"))
            .join(KillCase, KillCase.from_user_id == UserState.tg_id)
            .where(KillCase.status == KillCaseStatus.approved)
            .group_by(UserState.full_name)
            .order_by(func.count(KillCase.id).desc())
            .limit(5)
        )
    ).all()

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


PLAYERS_PAGE_SIZE = 10


class PlayersPageCallbackData(CallbackData, prefix="players_page"):
    page: int


async def players_page_view(
    session: AsyncSession, page: int
) -> tuple[str, InlineKeyboardMarkup | None]:
    where = (
        UserState.permission_key == PermissionKey.participant,
        UserState.form_accepted == True,  # noqa: E712
    )
    total = await session.scalar(select(func.count()).select_from(UserState).where(*where))
    alive = await session.scalar(
        select(func.count()).select_from(UserState).where(*where, UserState.killed == False)  # noqa: E712
    )
    pages = max(1, -(-total // PLAYERS_PAGE_SIZE))
    page = min(max(page, 0), pages - 1)

    players = list(
        await session.scalars(
            select(UserState)
            .where(*where)
            .order_by(col(UserState.killed), UserState.full_name)
            .offset(page * PLAYERS_PAGE_SIZE)
            .limit(PLAYERS_PAGE_SIZE)
        )
    )
    ids = [p.tg_id for p in players]

    targets = dict(
        (
            await session.execute(
                select(UserVictim.user_id, UserState.full_name)
                .join(UserState, UserState.tg_id == UserVictim.victim_id)
                .where(UserVictim.user_id.in_(ids), UserVictim.active)
            )
        ).all()
    )
    kills = dict(
        (
            await session.execute(
                select(KillCase.from_user_id, func.count())
                .where(
                    KillCase.from_user_id.in_(ids),
                    KillCase.status == KillCaseStatus.approved,
                )
                .group_by(KillCase.from_user_id)
            )
        ).all()
    )

    lines = [
        "👥 <b>Участники игры</b>",
        f"Всего: {total} | Живых: {alive} | Выбыло: {total - alive}",
        f"Страница {page + 1} из {pages}",
    ]
    for number, p in enumerate(players, page * PLAYERS_PAGE_SIZE + 1):
        status = "💀 выбыл" if p.killed else "✅ жив"
        target = "-" if p.killed else html.escape(targets.get(p.tg_id, "-"))
        lines.append(
            f"\n<b>{number}. {html.escape(p.full_name)}</b> ({html.escape(p.group)})\n"
            f"Статус: {status}\n"
            f"Жертва: {target}\n"
            f"Убийств: {kills.get(p.tg_id, 0)}\n"
            f"ID: <code>{p.tg_id}</code>"
        )
    if not players:
        lines.append("\nУчастников пока нет")

    buttons = []
    if page > 0:
        buttons.append(
            InlineKeyboardButton(
                text="Назад",
                callback_data=PlayersPageCallbackData(page=page - 1).pack(),
            )
        )
    if page < pages - 1:
        buttons.append(
            InlineKeyboardButton(
                text="Вперёд",
                callback_data=PlayersPageCallbackData(page=page + 1).pack(),
            )
        )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[buttons]) if buttons else None
    return "\n".join(lines), keyboard


@org_router.message(Command("players"))
async def players_list(message: Message, session: AsyncSession):
    text, keyboard = await players_page_view(session, 0)
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@org_router.callback_query(PlayersPageCallbackData.filter(), IsOrganizer())
async def players_list_page(
    callback: CallbackQuery,
    callback_data: PlayersPageCallbackData,
    session: AsyncSession,
):
    text, keyboard = await players_page_view(session, callback_data.page)
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


async def export_game(session: AsyncSession) -> GameState | None:
    game = await GameState.current_game(session)
    if game is not None and game.status != GameStatus.InvitationsPending:
        return game

    last_finished = await session.scalar(
        select(GameState)
        .where(GameState.status == GameStatus.Finalized)
        .order_by(GameState.ended_at.desc())
    )
    return last_finished or game


def build_export_csv(
    game: GameState,
    players: list[UserState],
    links: list[UserVictim],
    kills: list[KillCase],
) -> bytes:
    names = {p.tg_id: p.full_name for p in players}
    first_victim: dict[int, int] = {}
    current_victim: dict[int, int] = {}
    for link in links:
        first_victim.setdefault(link.user_id, link.victim_id)
        if link.active:
            current_victim[link.user_id] = link.victim_id

    victim_by_link = {link.id: link.victim_id for link in links}
    killed_by = {victim_by_link[k.user_victim_id]: k.from_user_id for k in kills}
    kill_counts = Counter(k.from_user_id for k in kills)

    def alive(player: UserState) -> bool:
        # the killed flag is reset when a game ends, so finished games rely on kill reports
        if game.status == GameStatus.Finalized:
            return player.tg_id not in killed_by
        return not player.killed

    def name(user_id: int | None) -> str:
        return names.get(user_id, "")

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "tg_id",
            "username",
            "full_name",
            "group",
            "alive",
            "first_target",
            "current_target",
            "kills",
            "killed_by",
        ]
    )
    for p in players:
        writer.writerow(
            [
                p.tg_id,
                p.tg_name,
                p.full_name,
                p.group,
                int(alive(p)),
                name(first_victim.get(p.tg_id)),
                name(current_victim.get(p.tg_id)),
                kill_counts[p.tg_id],
                name(killed_by.get(p.tg_id)),
            ]
        )

    return buf.getvalue().encode("utf-8-sig")


@org_router.message(Command("export"))
async def export(message: Message, session: AsyncSession):
    game = await export_game(session)
    if game is None:
        await message.answer("No games yet")
        return

    players = list(
        await session.scalars(
            select(UserState)
            .join(GameAndUsers, GameAndUsers.user_id == UserState.tg_id)
            .where(GameAndUsers.game_id == game.id)
            .order_by(UserState.full_name)
        )
    )
    if not players:
        await message.answer("No players in this game")
        return

    links = list(
        await session.scalars(
            select(UserVictim)
            .where(UserVictim.game_id == game.id)
            .order_by(UserVictim.created_at)
        )
    )
    kills = list(
        await session.scalars(
            select(KillCase).where(
                KillCase.status == KillCaseStatus.approved,
                col(KillCase.user_victim_id).in_([link.id for link in links]),
            )
        )
    )

    await message.answer_document(
        BufferedInputFile(
            build_export_csv(game, players, links, kills),
            filename=f"export_{game.id.hex[:8]}.csv",
        ),
        caption=f"{game.game_name} ({game.status.value}), players: {len(players)}",
    )


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


class EndGameAnswer(str, Enum):
    yes = "yes"
    no = "no"


class EndGameCallbackData(CallbackData, prefix="end_game"):
    answer: EndGameAnswer


def end_game_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Да",
                    callback_data=EndGameCallbackData(answer=EndGameAnswer.yes).pack(),
                ),
                InlineKeyboardButton(
                    text="Нет",
                    callback_data=EndGameCallbackData(answer=EndGameAnswer.no).pack(),
                ),
            ]
        ]
    )


@org_router.message(Command("end_game"))
async def end_game(message: Message, session: AsyncSession):
    if not await GameState.current_game(session):
        return await message.answer("Текущая игра не идет")

    await message.answer(
        "Вы уверены что хотите закончить текущую игру?",
        reply_markup=end_game_keyboard(),
    )


@org_router.callback_query(EndGameCallbackData.filter(), IsOrganizer())
async def waiting_for_answer(
    callback: CallbackQuery,
    callback_data: EndGameCallbackData,
    session: AsyncSession,
):
    await callback.message.edit_reply_markup(reply_markup=None)
    if callback_data.answer == EndGameAnswer.no:
        await callback.message.answer("Отмена закрытие текущей игры")
        return await callback.answer()

    if not await GameState.current_game(session):
        return await callback.answer("Текущая игра не идет", show_alert=True)

    await callback.message.answer(
        "Игра была закончена, всем участникам была отправлена их стаистика, новая игра в ожидании"
    )

    game = await GameState.close_the_game(session)

    query = select(UserState).where(UserState.games.any(id=game.id))
    users = (await session.scalars(query)).all()

    for user in users:
        killed_count = await session.scalar(
            select(func.count())
            .select_from(KillCase)
            .where(
                KillCase.status == KillCaseStatus.approved,
                KillCase.from_user_id == user.tg_id,
            )
        )
        text = f"Игра была закончена. вы убили {killed_count} человек потверждено, \n ГГ ВП"

        try:
            await callback.bot.send_message(user.tg_id, text)
        except TelegramAPIError:
            logger.info(f"Telegram user blocked this bot: {user.tg_id}")

    await GameState.start_next_game(session, "Цепочка убийств")

    await callback.message.answer("ГГ ВП")
    await callback.answer()
