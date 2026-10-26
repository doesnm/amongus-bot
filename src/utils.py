import uuid
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


def describe(user: UserState) -> str:
    return f"{user.full_name}, {user.group} (id {user.tg_id})"


class KillReviewAction(str, Enum):
    approve = "approve"
    reject = "reject"


class KillReviewCallbackData(CallbackData, prefix="kill_review"):
    action: KillReviewAction
    case_id: uuid.UUID


class KillVictimAnswer(str, Enum):
    confirm = "confirm"
    dispute = "dispute"


class KillVictimCallbackData(CallbackData, prefix="kill_victim"):
    answer: KillVictimAnswer
    case_id: uuid.UUID


def kill_review_keyboard(case_id: uuid.UUID) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="Принять",
            callback_data=KillReviewCallbackData(action=KillReviewAction.approve, case_id=case_id).pack(),
        ),
        InlineKeyboardButton(
            text="Отклонить",
            callback_data=KillReviewCallbackData(action=KillReviewAction.reject, case_id=case_id).pack(),
        ),
    ]])


def kill_victim_keyboard(case_id: uuid.UUID) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="Да, меня убили",
            callback_data=KillVictimCallbackData(answer=KillVictimAnswer.confirm, case_id=case_id).pack(),
        ),
        InlineKeyboardButton(
            text="Оспорить",
            callback_data=KillVictimCallbackData(answer=KillVictimAnswer.dispute, case_id=case_id).pack(),
        ),
    ]])
