import random
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, func

from src.models import UserState, UserVictim


class ChainError(Exception):
    pass


@dataclass
class Relink:
    hunter_id: int | None
    new_target_id: int | None


@dataclass
class RevertResult:
    applied: bool
    chain_changed: bool


async def get_link_by_hunter(session: AsyncSession, user_id: int) -> UserVictim | None:
    stmt = select(UserVictim).where(UserVictim.user_id == user_id, UserVictim.active)
    return (await session.scalars(stmt)).first()


async def get_link_by_victim(session: AsyncSession, victim_id: int) -> UserVictim | None:
    stmt = select(UserVictim).where(UserVictim.victim_id == victim_id, UserVictim.active)
    return (await session.scalars(stmt)).first()


async def get_target(session: AsyncSession, user_id: int) -> UserState | None:
    link = await get_link_by_hunter(session, user_id)
    if link is None:
        return None
    return await session.get(UserState, link.victim_id)


async def chain_size(session: AsyncSession) -> int:
    stmt = select(func.count()).select_from(UserVictim).where(UserVictim.active)
    return await session.scalar(stmt) or 0


async def build_chain(session: AsyncSession, user_ids: Sequence[int]) -> list[UserVictim]:
    if len(user_ids) < 2:
        raise ChainError("Для игры нужно минимум 2 участника")
    if await chain_size(session):
        raise ChainError("Цепочка уже построена")

    order = list(user_ids)
    random.shuffle(order)
    links = [
        UserVictim(user_id=hunter, victim_id=victim)
        for hunter, victim in zip(order, order[1:] + order[:1])
    ]
    session.add_all(links)
    await session.flush()
    return links


async def apply_kill(session: AsyncSession, link_id) -> Relink:
    link = await session.get(UserVictim, link_id)
    if link is None or not link.active:
        raise ChainError("Эта жертва уже не актуальна - цепочка изменилась")

    victim = await session.get(UserState, link.victim_id)
    victim.killed = True
    link.active = False

    new_target_id = None
    victim_link = await get_link_by_hunter(session, link.victim_id)
    if victim_link is not None:
        victim_link.active = False
        if victim_link.victim_id != link.user_id:
            session.add(UserVictim(user_id=link.user_id, victim_id=victim_link.victim_id))
            new_target_id = victim_link.victim_id

    await session.flush()
    return Relink(hunter_id=link.user_id, new_target_id=new_target_id)


async def remove_from_chain(session: AsyncSession, user_id: int) -> Relink:
    user = await session.get(UserState, user_id)
    if user is None:
        raise ChainError("Игрок не найден")

    incoming = await get_link_by_victim(session, user_id)
    outgoing = await get_link_by_hunter(session, user_id)
    if incoming is None and outgoing is None:
        raise ChainError("Игрок не находится в цепочке")

    user.killed = True
    for link in (incoming, outgoing):
        if link is not None:
            link.active = False

    hunter_id = incoming.user_id if incoming else None
    new_target_id = None
    if incoming and outgoing and incoming.user_id != outgoing.victim_id:
        session.add(UserVictim(user_id=incoming.user_id, victim_id=outgoing.victim_id))
        new_target_id = outgoing.victim_id

    await session.flush()
    return Relink(hunter_id=hunter_id, new_target_id=new_target_id)


async def revert_kill(session: AsyncSession, link_id, force: bool = False) -> RevertResult:
    link = await session.get(UserVictim, link_id)
    if link is None:
        raise ChainError("Звено не найдено")
    if link.active:
        raise ChainError("Убийство не было засчитано")

    hunter = await session.get(UserState, link.user_id)
    victim = await session.get(UserState, link.victim_id)
    if not victim.killed or await get_link_by_hunter(session, victim.tg_id):
        raise ChainError("Жертва уже в игре")

    stmt = (
        select(UserVictim)
        .where(UserVictim.user_id == victim.tg_id)
        .order_by(UserVictim.created_at.desc())
    )
    victim_old_link = (await session.scalars(stmt)).first()
    old_target_id = victim_old_link.victim_id if victim_old_link else hunter.tg_id

    hunter_link = await get_link_by_hunter(session, hunter.tg_id)
    current_target_id = hunter_link.victim_id if hunter_link else hunter.tg_id
    chain_changed = hunter.killed or current_target_id != old_target_id

    if chain_changed and not force:
        return RevertResult(applied=False, chain_changed=True)
    if hunter.killed:
        raise ChainError("Убийца уже выбыл - вернуть жертву после него нельзя")

    if hunter_link is not None:
        hunter_link.active = False
    session.add(UserVictim(user_id=hunter.tg_id, victim_id=victim.tg_id))
    session.add(UserVictim(user_id=victim.tg_id, victim_id=current_target_id))
    victim.killed = False

    await session.flush()
    return RevertResult(applied=True, chain_changed=chain_changed)
