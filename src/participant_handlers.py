from html import escape

import structlog
from aiogram import Bot, Router, F
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import (
    CallbackQuery,
    ForceReply,
    Message,
    InlineQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from sqlalchemy.ext.asyncio import AsyncSession
from aiogram.exceptions import TelegramAPIError
from sqlmodel import select, func, col

from src import chain
from src.config import get_config
from src.fsm_states import KillFsm, StartFsm
from src.filters import IsRegistered
from src.models import (
    GameAndUsers,
    GameState,
    GameStatus,
    KillCase,
    KillCaseStatus,
    PermissionKey,
    UserState,
    UserVictim,
)
from src.utils import (
    notify_new_form,
    NewFormCallbackData,
    NewFormTypes,
    describe,
    KillVictimCallbackData,
    KillVictimAnswer,
    edit_org_report,
    kill_report_text,
    kill_review_keyboard,
    kill_victim_keyboard,
)

participant_router = Router()
logger = structlog.get_logger(__name__)


@participant_router.message(CommandStart())
async def start_message(message: Message, state: FSMContext, session: AsyncSession):

    if message.from_user:
        user_id = message.from_user.id

        existing = await session.get(UserState, user_id)
        if existing is None or existing.form_accepted is False:
            if message.chat.type != ChatType.PRIVATE:
                return await message.answer(
                    "Отправьте в ЛС для регистрации вашей фур персоны"
                )
            await state.clear()
            await message.answer("Привет! Напиши своё полное имя: ")
            await state.set_state(StartFsm.put_fullname)
        else:
            if existing.form_accepted:
                await message.answer(
                    "✅ <b>Вы уже зарегистрированы</b>\n\n"
                    f"Игрок: {escape(existing.full_name)}\n"
                    f"Группа: {escape(existing.group)}\n\n"
                    "Все команды: /help",
                    parse_mode="HTML",
                )
            else:
                await message.answer(
                    "⏳ <b>Заявка на рассмотрении</b>\n\n"
                    "Вы уже подали заявку на регистрацию. "
                    "Дождитесь решения организаторов.",
                    parse_mode="HTML",
                )


@participant_router.message(StartFsm.put_group, F.text)
async def enter_group(message: Message, state: FSMContext, session: AsyncSession):
    text = message.text.strip()

    if len(text.split("=")) != 2 and len(text.split("-")) != 2:
        await message.answer("Неправильно написанная группа")
        await state.clear()
        return

    data = await state.update_data(group=message.text)

    tg_user = message.from_user

    if tg_user:
        tg_name = tg_user.username if tg_user.username else "username нет"

        # отклонённый пользователь остаётся в БД, поэтому повторная заявка обновляет его запись
        user = await session.get(UserState, tg_user.id)
        if user is None:
            user = UserState(
                tg_id=tg_user.id,
                permission_key=PermissionKey.user,
                tg_name=tg_name,
                killed=False,
                full_name=data["fullname"],
                group=data["group"],
                form_accepted=None,
            )
        elif user.form_accepted is False:
            user.tg_name = tg_name
            user.full_name = data["fullname"]
            user.group = data["group"]
            user.form_accepted = None
            user.reject_reason = None
        else:
            await state.clear()
            return await message.answer("Ваша заявка уже подана")

        session.add(user)

        await message.answer("Ваша форма к регистрации на ожидании у организаторов")
        await notify_new_form(message.bot, user)

        await state.clear()


@participant_router.message(StartFsm.put_fullname, F.text)
async def enter_fullname(message: Message, state: FSMContext):
    text = message.text.strip()

    if not len(text.split()) in {2, 3}:
        await message.answer("Вы неправильно написали свое ФИО")
        await state.clear()
        return

    await state.update_data(fullname=message.text)
    await state.set_state(StartFsm.put_group)
    await message.answer("Напиши свою группу (например SE-2614):")


@participant_router.callback_query(NewFormCallbackData.filter())
async def new_form_handler(cb: CallbackQuery, session: AsyncSession):
    user = await session.get(UserState, cb.from_user.id)
    if user is None:
        await cb.answer("Вы не зарегистрированы")
        return
    if user.permission_key != PermissionKey.organizer:
        await cb.answer("Вы не являетесь оргнизатором")
        return

    data = NewFormCallbackData.unpack(cb.data)

    user = await session.get(UserState, data.user_id)
    if user is None or user.form_accepted is not None:
        await cb.message.edit_reply_markup(reply_markup=None)
        await cb.answer("Эта заявка уже рассмотрена", show_alert=True)
        return

    reviewer = escape(cb.from_user.full_name)
    if data.answer_type == NewFormTypes.deny:
        await cb.bot.send_message(data.user_id, "Ваша заявка была отклонена")

        user.form_accepted = False
        verdict = f"Отклонён ({reviewer})"
    else:
        await cb.bot.send_message(
            data.user_id, "Ваше участие было принято в текущую игру, ожидайте"
        )
        user.form_accepted = True
        user.permission_key = PermissionKey.participant
        session.add(
            GameAndUsers(
                user_id=user.tg_id, game_id=(await GameState.current_game(session)).id
            )
        )
        verdict = f"Принят ({reviewer})"

    session.add(user)
    await cb.message.edit_text(
        f"{cb.message.html_text}\n\n{verdict}", parse_mode="HTML", reply_markup=None
    )
    await cb.answer()


@participant_router.message(Command("target"), IsRegistered())
async def target_handler(message: Message, session: AsyncSession):
    if message.from_user:
        target = await chain.get_target(session, message.from_user.id)
        if target is None:
            await message.answer("У тебя сейчас нет жертвы")
            return
        await message.answer(
            "🎯 <b>Твоя жертва</b>\n\n"
            f"{escape(target.full_name)}\n"
            f"Группа: {escape(target.group)}\n\n"
            "Когда выполнишь задание, отправь /kill",
            parse_mode="HTML",
        )


@participant_router.message(Command("kill"), IsRegistered())
async def kill_handler(message: Message, session: AsyncSession, state: FSMContext):
    game = await GameState.current_game(session)
    if game is None or game.status != GameStatus.GameIsGoing:
        return await message.answer("Игра сейчас не идёт")

    user = await session.get(UserState, message.from_user.id)
    if user.permission_key != PermissionKey.participant or user.killed:
        return await message.answer("Ты не участвуешь в игре или уже выбыл")

    pending = await session.scalar(
        select(KillCase.id).where(
            KillCase.from_user_id == user.tg_id,
            col(KillCase.status).in_((KillCaseStatus.disputed,)),
        )
    )
    if pending is not None:
        return await message.answer(
            "У тебя уже есть отчёт на пере расмотрении, дождись решения организаторов"
        )

    target = await chain.get_target(session, user.tg_id)
    if target is None:
        return await message.answer("У тебя сейчас нет жертвы")

    await state.set_state(KillFsm.wait_evidence)
    await message.answer(
        "🔪 <b>Отчёт об убийстве</b>\n\n"
        f"Жертва: {escape(target.full_name)}\n\n"
        "Пришли совместное фото или кружок с ней.\n"
        "Любое другое сообщение отменит отчёт.",
        parse_mode="HTML",
    )


@participant_router.callback_query(KillVictimCallbackData.filter())
async def kill_victim_handler(
    callback: CallbackQuery,
    callback_data: KillVictimCallbackData,
    session: AsyncSession,
    bot: Bot,
):
    case = await session.get(KillCase, callback_data.case_id)
    link = await session.get(UserVictim, case.user_victim_id) if case else None
    if link is None or link.victim_id != callback.from_user.id:
        return await callback.answer("Отчёт не найден", show_alert=True)

    await callback.message.edit_reply_markup(reply_markup=None)
    if case.status != KillCaseStatus.pending:
        return await callback.answer(
            "По этому отчёту уже есть решение", show_alert=True
        )

    hunter = await session.get(UserState, case.from_user_id)
    victim = await session.get(UserState, link.victim_id)

    if callback_data.answer == KillVictimAnswer.dispute:
        case.status = KillCaseStatus.disputed
        victim_text = "Ты оспорил убийство. Организаторы рассмотрят отчёт"
        org_note = "Жертва ОСПОРИЛА убийство"
    else:
        victim_text = "Ты подтвердил убийство. Ждём решения организаторов"
        org_note = "Жертва подтвердила убийство"

    await callback.message.edit_text(victim_text)
    await edit_org_report(
        bot,
        case,
        f"{kill_report_text(hunter, victim, case)}\n\n{org_note}",
        reply_markup=kill_review_keyboard(case.id),
    )
    await callback.answer()


@participant_router.message(Command("me"), IsRegistered())
async def profile_handler(message: Message, session: AsyncSession):
    user = await session.get(UserState, message.from_user.id)
    kills = await session.scalar(
        select(func.count())
        .select_from(KillCase)
        .where(
            KillCase.status == KillCaseStatus.approved,
            KillCase.from_user_id == user.tg_id,
        )
    )
    victim = await chain.get_target(session, user.tg_id)
    if victim:
        target_text = (
            f"{escape(victim.full_name)} ({escape(victim.group)})\n"
            f"Telegram: {'@' + escape(victim.tg_name) if ' ' not in victim.tg_name else 'username нет'}"
        )
    else:
        target_text = "нет"

    await message.answer(
        "👤 <b>Твой профиль</b>\n\n"
        f"Имя: {escape(user.full_name)}\n"
        f"Группа: {escape(user.group)}\n"
        f"Статус: {'💀 выбыл' if user.killed else '✅ жив'}\n"
        f"Убийств: {kills}\n\n"
        f"🎯 <b>Текущая цель</b>\n{target_text}",
        parse_mode="HTML",
    )


game_explanation = """
🎯 <b>Суть игры</b>

Игра проходит <b>в здании университета</b>. Для участия зарегистрируйся в боте.

Каждый получает свою жертву, но не знает, кто охотится за ним.

Найди жертву без компании людей, скажи "ЧАС ПРОБИЛ", сделайте совместное фото и отправь через /kill.

После одобрения организатором жертва выбывает, а ты получаешь ее цель. Последние двое играют финал по особым правилам - см. ниже.
""".strip()

game_rules = """
📜 <b>Правила игры</b>

<b>1. Обычное убийство</b>
Найди свою жертву, когда она одна, без компании других людей. Подойди, скажи «ЧАС ПРОБИЛ», сделайте совместное фото, на котором чётко видны ваши лица. Отправь фото через /kill.

<b>2. Если тебя нашли</b>
Если всё произошло по правилам, нельзя отказываться и убегать. Подтверди отчёт в боте. Если считаешь, что правила нарушены, нажми «Оспорить». На время рассмотрения отчета приостанови свою охоту.

<b>3. Подтверждение и выбывание</b>
Убийство засчитывается только после проверки организатором. После одобрения жертва выбывает, а охотник автоматически получает её цель. Выбывшие вне игры.

<b>4. Отчёты</b>
У одного игрока может быть только один отчёт на рассмотрении. Пока по нему нет решения, повторные отчёты отправлять нельзя.

<b>5. Запрет на кемпинг</b>
Нельзя специально отсиживаться более 5 минут или в недоступном месте, чтобы тебя невозможно было найти, а также караулить.

<b>6. Нарушения</b>
Запрещены любые виды насилия или принуждения, подделка доказательств и обман организаторов. Запрещается мешать работе университета.

<b>7. Финал: последние двое</b>
Когда остаются двое, организатор объявляет в общем чате начало финала и точное время его окончания — через 30 минут.

С этого объявления нужно первым сфотографировать своего соперника и отправить через /kill. Лицо должно быть отчетливым. Совместное фото и условие «жертва одна» в финале не требуются. Остальные запреты продолжают действовать.

<b>8. Победа по фотографии</b>
В финале побеждает автор первого подходящего под правила фото. Учитывается время отправки отчёта в бота.

Если оба отчета были сделаны одновременно, организатор сначала рассматривает более ранний отчёт.

<b>9. Победа</b>
Если за 30 минут ни один финалист не отправил подходящий отчет, побеждает тот из них, у кого больше засчитанных убийств за текущую игру. При равном количестве объявляется ничья.

<b>10. Решение организатора</b>
Окончательное решение по доказательствам, нарушениям, спорам и результатам принимает организатор. Организатор вправе исключить игрока за нарушения. 
""".strip()


@participant_router.message(Command("rules"))
async def rules_handler(message: Message):
    await message.answer(game_explanation, parse_mode="HTML")
    await message.answer(game_rules, parse_mode="HTML")


@participant_router.message(Command("help"))
async def help_handler(message: Message, session: AsyncSession):
    lines = [
        "📖 <b>Команды бота</b>",
        "",
        "<b>Для всех</b>",
        "/start - регистрация (ФИО и группа), статус заявки",
        "/rules - правила игры",
        "/help - этот список",
        "",
        "<b>Для участников</b>",
        "/me - профиль: статус, число убийств, текущая цель",
        "/target - узнать свою жертву",
        "/kill - отчёт об убийстве: пришли фото или кружок с жертвой, "
        "жертва подтвердит, организаторы засчитают",
    ]

    user = await session.get(UserState, message.from_user.id) if message.from_user else None
    if user is not None and user.permission_key == PermissionKey.organizer:
        lines += [
            "",
            "🛠 <b>Для организаторов</b>",
            "/start_game - начать игру: собрать цепочку из принятых участников",
            "/end_game - завершить игру досрочно (с подтверждением), "
            "участникам уйдёт статистика, откроется новая игра",
            "/players - участники: статус, жертва, убийства (по страницам)",
            "/game_stats - сводка: участники, живые, убийства, топ убийц",
            "/kick &lt;tg_id&gt; - исключить игрока, цепочка перестроится",
            "/broadcast &lt;текст&gt; - рассылка всем пользователям бота",
            "/export - CSV с участниками, цепочкой и убийствами игры",
            "",
            "Заявки на регистрацию и отчёты об убийствах приходят в чат "
            "организаторов с кнопками решения.",
        ]

    await message.answer("\n".join(lines), parse_mode="HTML")


# Хендлеры состояния стоят в конце, чтобы команды выше срабатывали раньше них
@participant_router.message(KillFsm.wait_evidence, F.photo | F.video_note)
async def kill_evidence_handler(
    message: Message, session: AsyncSession, state: FSMContext, bot: Bot
):
    await state.clear()

    link = await chain.get_link_by_hunter(session, message.from_user.id)
    if link is None:
        return await message.answer("У тебя сейчас цели")

    hunter = await session.get(UserState, link.user_id)
    victim = await session.get(UserState, link.victim_id)
    case = KillCase(
        from_user_id=hunter.tg_id,
        evidence_id=message.photo[-1].file_id
        if message.photo
        else message.video_note.file_id,
        user_victim_id=link.id,
        approved_at=None,
    )
    session.add(case)

    text = kill_report_text(hunter, victim, case)
    org_chat_id = get_config().org_chat_id
    if message.photo:
        report = await bot.send_photo(
            org_chat_id,
            case.evidence_id,
            caption=text,
            reply_markup=kill_review_keyboard(case.id),
        )
    else:
        await bot.send_video_note(org_chat_id, case.evidence_id)
        report = await bot.send_message(
            org_chat_id, text, reply_markup=kill_review_keyboard(case.id)
        )
    case.org_message_id = report.message_id
    case.org_message_is_photo = bool(message.photo)

    try:
        question = await bot.send_message(
            victim.tg_id,
            f"{hunter.full_name} сообщает что жесточайшим методом убил тебя. Это правда?",
            reply_markup=kill_victim_keyboard(case.id),
        )
        case.victim_message_id = question.message_id
    except TelegramAPIError:
        logger.warning("Failed to notify victim", user_id=victim.tg_id, exc_info=True)

    await message.answer("Отчёт отправлен организаторам жди решения")


@participant_router.message(KillFsm.wait_evidence)
async def kill_cancel_handler(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Нужно было фото или кружок. Отчёт отменён, начни заново с /kill"
    )
