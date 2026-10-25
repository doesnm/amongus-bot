from aiogram.filters import Filter
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import PermissionKey, UserState

class IsRegistered(Filter):
    async def __call__(self, message: Message, session: AsyncSession) -> bool:
        user = message.from_user
        if user is None:
            return False

        user_id = user.id

        return bool(await session.get(UserState, user_id))


class IsOrganizer(Filter):
    async def __call__(self, message: Message, session: AsyncSession) -> bool:
        user = message.from_user
        if user is None:
            return False

        state = await session.get(UserState, user.id)
        return state is not None and state.permission_key == PermissionKey.organizer


class isSuperOrganizer(Filter): 
    async def __call__(self, message: Message, config) -> bool: 
        if message.from_user is None: 
            return False 

        return message.from_user.id == config.super_organizer