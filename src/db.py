from collections.abc import Awaitable, Callable
from typing import Any

from aiogram.types import TelegramObject, Update
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession, create_async_engine
from sqlmodel import SQLModel

from src.config import Config
from src.logger import logger
from src.models import GameState, PermissionKey, UserState


async def init_db(config: Config) -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///amongus_bot.db")

    return async_sessionmaker(engine, expire_on_commit=False)


async def ensure_root_org(db: async_sessionmaker[AsyncSession], config: Config) -> None:
    if not config.root_org_ids:
        return

    async with db.begin() as session:
        for tg_id in config.root_org_ids:
            user = await session.get(UserState, tg_id)
            if user is None:
                user = UserState(
                    tg_id=tg_id,
                    tg_name="root_org",
                    full_name="Организатор",
                    group="-",
                    form_accepted=True,
                )
            user.permission_key = PermissionKey.organizer
            session.add(user)

            logger.info("root organizer added", tg_id=tg_id)


async def ensure_current_game(db: async_sessionmaker[AsyncSession]) -> None:
    async with db.begin() as session:
        if await GameState.current_game(session) is None:
            game = GameState(game_name="Amongus")
            session.add(game)


async def begin_sessionmaker(
    handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
    event: TelegramObject,
    data: dict[str, Any],
) -> None:
    if isinstance(event, Update):
        logger.info("Session maker has started")

        async with data["db"].begin() as session:
            data["session"] = session
            return await handler(event, data)
    return await handler(event, data)
