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

        is_registred = bool(await session.get(UserState, user_id))

        if not is_registred:
            message.answer("Пожалуйста зарегистрируйтесь.")

        return is_registred


class IsOrganizer(Filter):
    async def __call__(self, message: Message, session: AsyncSession) -> bool:
        user = message.from_user
        if user is None:
            return False

        state = await session.get(UserState, user.id)

        is_organiser = (
            state is not None and state.permission_key == PermissionKey.organizer
        )

        return is_organiser
