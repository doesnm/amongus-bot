from enum import Enum
from html import escape

from aiogram import Bot
from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from src.config import get_config
from src.models import UserState


class NewFormTypes(str, Enum):
    deny = "deny"
    accept = "accept"


class NewFormCallbackData(CallbackData, prefix="new_form"):
    answer_type: NewFormTypes
    user_id: int


async def notify_new_form(bot: Bot, user: UserState):
    text = (
        "Новый пользователь хочет зайти в будущую игру\n"
        f"user_id: <code>{user.tg_id}</code>, username: @{escape(user.tg_name)}\n"
        f"Группа: {escape(user.group)}\n"
        f"ФИО: {escape(user.full_name)}"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="Одобрить",
                callback_data=NewFormCallbackData(answer_type=NewFormTypes.accept, user_id=user.tg_id).pack(),
            ),
            InlineKeyboardButton(
                text="Отклонить",
                callback_data=NewFormCallbackData(answer_type=NewFormTypes.deny, user_id=user.tg_id).pack(),
            ),
        ]
    ])

    await bot.send_message(get_config().org_chat_id, text, reply_markup=keyboard, parse_mode="HTML")
