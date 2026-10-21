import asyncio
import os

import dotenv
import structlog
from aiogram import Dispatcher, Bot, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message
from sqlmodel import SQLModel

dotenv.load_dotenv()

logger = structlog.get_logger(__name__)
TOKEN = os.environ.get("BOT_TOKEN", "")
root_router = Router(name="root_router")



async def init_db():
    pass

async def main():
    logger.info("Starting bot")

    dp = Dispatcher(context=SQLModel())

    bot = Bot(
        token=TOKEN,
    )

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
