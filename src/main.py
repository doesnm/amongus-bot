import asyncio

from colorama import initialise
import dotenv
import structlog
from aiogram import Dispatcher, Bot, Router

from src.logger import logger
from src.db import begin_sessionmaker, ensure_current_game, ensure_root_org, init_db
from src.organizer_handlers import org_router
from src.participant_handlers import participant_router
from src.config import Config

dotenv.load_dotenv()

root_router = Router(name="root_router")


async def launch_bot():
    logger.info("Starting bot")

    config = Config()

    structlog.configure_once(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S", utc=False),
            structlog.processors.StackInfoRenderer(),
            (
                structlog.dev.ConsoleRenderer()
                if config.environment_profile == "DEV"
                else structlog.processors.JSONRenderer()
            ),
        ]
    )

    db = await init_db(config)
    await ensure_root_org(db, config)
    await ensure_current_game(db)

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
