import structlog
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

org_router = Router(name="org_router")
logger = structlog.get_logger(__name__)


@org_router.message(Command("kick"))
async def kick_participant(message: Message):
    pass


@org_router.message(Command("stats"))
async def game_stats(message: Message):
    pass


@org_router.message(Command("export"))
async def export(message: Message):
    pass


@org_router.message(Command("broadcast"))
async def broadcast(message: Message):
    pass


@org_router.message(Command("end_game"))
async def end_game(message: Message):
    pass
