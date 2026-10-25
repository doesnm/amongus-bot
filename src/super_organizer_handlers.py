import structlog 
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from src.filters import isSuperOrganizer

super_org_router = Router(name="super_org_router")
super_org_router.message.filter(isSuperOrganizer())
logger = structlog.get_logger(__name__)

@super_org_router.message(Command("mk_org"))
async def make_organizer(message: Message):
    pass


@super_org_router.message(Command("rm_org"))
async def remove_organizer(message: Message):
    pass