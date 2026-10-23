from collections.abc import Awaitable, Callable
from typing import Any

from aiogram.types import TelegramObject, Update
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession, create_async_engine
from sqlmodel import SQLModel

from src.config import Config
from src.logger import logger


async def init_db(config: Config) -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///amongus_bot.db")

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    return async_sessionmaker(engine, expire_on_commit=False)


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
