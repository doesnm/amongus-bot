import uuid
from enum import Enum
from html import escape

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from src.config import get_config
from src.logger import logger
from src.models import KillCase, UserState


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


def kill_report_text(hunter: UserState, victim: UserState, case: KillCase) -> str:
    return (
        "Отчёт об убийстве\n"
        f"Убийца: {describe(hunter)}\n"
        f"Жертва: {describe(victim)}\n"
        f"Время: {case.sent_at.astimezone():%d.%m.%Y %H:%M}"
    )


async def edit_org_report(
    bot: Bot,
    case: KillCase,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    if case.org_message_id is None:
        return
    chat_id = get_config().org_chat_id
    try:
        if case.org_message_is_photo:
            await bot.edit_message_caption(
                chat_id=chat_id,
                message_id=case.org_message_id,
                caption=text,
                reply_markup=reply_markup,
            )
        else:
            await bot.edit_message_text(
                text,
                chat_id=chat_id,
                message_id=case.org_message_id,
                reply_markup=reply_markup,
            )
    except TelegramAPIError:
        logger.warning("Failed to edit org report", case_id=str(case.id), exc_info=True)


async def edit_victim_question(bot: Bot, case: KillCase, victim_id: int, text: str) -> bool:
    """Replaces the victim's question and removes its buttons; False if it can't be edited."""
    if case.victim_message_id is None:
        return False
    try:
        await bot.edit_message_text(
            text, chat_id=victim_id, message_id=case.victim_message_id, reply_markup=None
        )
    except TelegramAPIError:
        logger.warning("Failed to edit victim message", case_id=str(case.id), exc_info=True)
        return False
    return True
