import asyncio
from typing import Any

import dotenv
import structlog
from aiogram import Dispatcher, Bot, Router
from aiogram.types import Update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from src.organizer_handlers import org_router
from src.participant_handlers import participant_router
from src.config import Config

dotenv.load_dotenv()


logger = structlog.get_logger(__name__)
root_router = Router(name="root_router")


async def init_db(config: Config) -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///amongus_bot.db")

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    return async_sessionmaker(engine, expire_on_commit=False)


async def begin_sessionmaker(handler: Any, event: Update, data: dict) -> None:
    logger.info("Session maker has started")

    async with data["db"].begin() as session:
        data["session"] = session
        return await handler(event, data)

async def launch_bot():
    logger.info("Starting bot")

    config = Config()

    structlog.configure_once(processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S", utc=False),
        structlog.processors.StackInfoRenderer(),
        structlog.dev.ConsoleRenderer()
            if config.environment_profile == "DEV" else structlog.processors.JSONRenderer(),
    ])


    db = await init_db(config)

    dp = Dispatcher(db=db)
    dp.update.middleware.register(begin_sessionmaker)

    dp.include_routers(org_router, participant_router)

    bot = Bot(
        token=config.bot_token,
    )

    try:
        me = await bot.get_me()
        logger.info("Configuration was completed", username=me.username)
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

def main():
    try:
        asyncio.run(launch_bot())
    except KeyboardInterrupt:
        logger.info("Bot stopped")


if __name__ == "__main__":
    main()
