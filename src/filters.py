from aiogram.filters import Filter
from aiogram.types import Message, TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession

from models import UserState


class IsRegistered(Filter):
    async def __call__(self, message: Message, session: AsyncSession) -> bool:
        user = message.from_user
        if user is None:
            return False

        user_id = user.id

        return bool(await session.get(UserState, user_id))
