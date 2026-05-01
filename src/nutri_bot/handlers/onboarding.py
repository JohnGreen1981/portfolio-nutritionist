from __future__ import annotations

import asyncio
import logging
from datetime import date

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from timezonefinder import TimezoneFinder
from geopy.geocoders import Nominatim

from ..repo import profiles as prof_repo
from ..nutrition import calc_targets
from ..schemas import Profile
from ..filters import OnboardingNotDone
from ..keyboards import MAIN_KB

log = logging.getLogger("nutri_bot.onboarding")
router = Router(name="onboarding")

_tf = TimezoneFinder()
_geo = Nominatim(user_agent="nutri-bot")

# ── step order ────────────────────────────────────────────────────────────────
STEPS = [
    "q_sex", "q_birth_year", "q_height", "q_weight", "q_body_type",
    "q_activity", "q_goal", "q_target_weight", "q_meal_regime",
    "q_timezone", "q_allergies", "q_diet_restrictions",
    "q_foods_liked", "q_foods_disliked",
]
STEP_NUM = {s: i + 1 for i, s in enumerate(STEPS)}

# ── keyboards ─────────────────────────────────────────────────────────────────
def _ik(*rows: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=d) for t, d in row] for row in rows]
    )

KB_DISCLAIMER = _ik([("✅ Принимаю", "ob:disclaimer:accept")])

KB_SEX = _ik([("♂ Мужской", "ob:sex:m"), ("♀ Женский", "ob:sex:f")])

KB_BODY = _ik(
    [("Худощавое", "ob:body_type:slim"), ("Среднее", "ob:body_type:medium"), ("Плотное", "ob:body_type:solid")]
)

KB_ACTIVITY = _ik(
    [("Сидячий", "ob:activity:sedentary"), ("Лёгкий", "ob:activity:light")],
    [("Умеренный", "ob:activity:moderate")],
    [("Высокий", "ob:activity:high"), ("Очень высокий", "ob:activity:very_high")],
)

KB_GOAL = _ik(
    [("📉 Снижение", "ob:goal:lose"), ("⚖️ Удержание", "ob:goal:maintain"), ("📈 Набор", "ob:goal:gain")]
)

KB_MEAL = _ik(
    [("3 раза в день", "ob:meal:3x"), ("4–5 раз", "ob:meal:4_5x")],
    [("Интервальное (16/8)", "ob:meal:intermittent"), ("Нерегулярно", "ob:meal:irregular")],
)

KB_DIET = [
    ("Нет ограничений", "none"), ("Веган", "vegan"), ("Вегетарианец", "vegetarian"),
    ("Кето", "keto"), ("Без глютена", "gluten_free"), ("ПП", "pp"), ("Другое", "other"),
]

def diet_kb(selected: list[str]) -> InlineKeyboardMarkup:
    rows = []
    for label, val in KB_DIET:
        mark = "✅ " if val in selected else ""
        rows.append([InlineKeyboardButton(text=f"{mark}{label}", callback_data=f"ob:diet:{val}")])
    rows.append([InlineKeyboardButton(text="Готово ➡️", callback_data="ob:diet:done")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

KB_LOCATION = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="📍 Поделиться локацией", request_location=True)]],
    resize_keyboard=True,
    one_time_keyboard=True,
)

# ── questions text ─────────────────────────────────────────────────────────────
def _question(step: str, num: int) -> str:
    prefix = f"<b>Вопрос {num} из 14:</b>\n\n"
    q = {
        "q_sex":        "Для начала — твой пол?",
        "q_birth_year": "В каком году ты родился? Просто число, например 1990.",
        "q_height":     "Твой рост в см?",
        "q_weight":     "Текущий вес в кг? Можно с десятой долей.",
        "q_body_type":  "Как бы ты описал своё телосложение?",
        "q_activity":   (
            "Насколько ты активен в обычную неделю?\n"
            "<i>Сидячий</i> — офис без прогулок · <i>Лёгкий</i> — 1–2 тренировки · "
            "<i>Умеренный</i> — 3–4 тренировки · <i>Высокий</i> — 5–6 тренировок · "
            "<i>Очень высокий</i> — ежедневно или физический труд"
        ),
        "q_goal":       "Какая цель сейчас?",
        "q_target_weight": "К какому весу хочешь прийти? В кг.",
        "q_meal_regime": "Как обычно питаешься?",
        "q_timezone":   (
            "Откуда ты? Самый простой способ — поделиться геопозицией, "
            "я сам определю часовой пояс.\nИли напиши название города текстом."
        ),
        "q_allergies":  "Есть ли аллергии или непереносимости? Например: лактоза, орехи, глютен. Если нет — напиши «нет».",
        "q_diet_restrictions": "Придерживаешься какого-то стиля питания? Можно выбрать несколько.",
        "q_foods_liked": "Какие 3–5 продуктов или блюд ты любишь больше всего? Перечисли через запятую.",
        "q_foods_disliked": "А что не любишь или стараешься избегать? Если всё ешь — напиши «всё ок».",
    }
    return prefix + q[step]


def _kb(step: str, selected: list[str] | None = None):
    mapping = {
        "q_sex": KB_SEX,
        "q_body_type": KB_BODY,
        "q_activity": KB_ACTIVITY,
        "q_goal": KB_GOAL,
        "q_meal_regime": KB_MEAL,
        "q_timezone": KB_LOCATION,
        "q_diet_restrictions": diet_kb(selected or []),
    }
    return mapping.get(step)


# ── helpers ───────────────────────────────────────────────────────────────────
async def _send_step(msg_or_cq: Message | CallbackQuery, step: str, selected: list[str] | None = None) -> None:
    num = STEP_NUM[step]
    text = _question(step, num)
    kb = _kb(step, selected)

    if isinstance(msg_or_cq, CallbackQuery):
        send = msg_or_cq.message.answer
    else:
        send = msg_or_cq.answer

    if kb is None:
        await send(text, parse_mode="HTML", reply_markup=ReplyKeyboardRemove())
    elif isinstance(kb, ReplyKeyboardMarkup):
        await send(text, parse_mode="HTML", reply_markup=kb)
    else:
        await send(text, parse_mode="HTML", reply_markup=kb)


async def _next_step(msg_or_cq: Message | CallbackQuery, profile: Profile, step: str) -> None:
    idx = STEPS.index(step) + 1
    if idx >= len(STEPS):
        await _finish(msg_or_cq, profile)
        return
    next_step = STEPS[idx]
    # skip target_weight if goal=maintain
    if next_step == "q_target_weight" and profile.goal == "maintain":
        idx += 1
        next_step = STEPS[idx]

    tid = profile.telegram_id
    profile = await prof_repo.update(tid, onboarding_step=next_step)
    await _send_step(msg_or_cq, next_step)


async def _finish(msg_or_cq: Message | CallbackQuery, profile: Profile) -> None:
    kcal, prot, fat, carb = calc_targets(profile)
    profile = await prof_repo.finish_onboarding(profile.telegram_id, kcal, prot, fat, carb)
    age = date.today().year - profile.birth_year

    GOAL_RU = {"lose": "Снижение веса", "maintain": "Удержание", "gain": "Набор массы"}
    ACTIVITY_RU = {
        "sedentary": "Сидячий", "light": "Лёгкий", "moderate": "Умеренный",
        "high": "Высокий", "very_high": "Очень высокий",
    }
    BODY_RU = {"slim": "Худощавое", "medium": "Среднее", "solid": "Плотное"}
    SEX_RU = {"m": "мужской", "f": "женский"}
    MEAL_RU = {"3x": "3 раза в день", "4_5x": "4–5 раз", "intermittent": "Интервальное (16/8)", "irregular": "Нерегулярно"}

    target_w_line = f" → {profile.target_weight_kg} кг" if profile.target_weight_kg else ""
    diet = ", ".join(profile.diet_restrictions) if profile.diet_restrictions else "нет"

    split = {"lose": (25, 30, 45), "maintain": (20, 30, 50), "gain": (25, 25, 50)}[profile.goal]

    text = (
        "Готово! Вот что у меня получилось:\n\n"
        f"<b>Профиль:</b> {SEX_RU[profile.sex]}, {age} лет, {int(profile.height_cm)} см, {profile.weight_kg} кг, {BODY_RU[profile.body_type]}\n"
        f"<b>Активность:</b> {ACTIVITY_RU[profile.activity_level]} · <b>Цель:</b> {GOAL_RU[profile.goal]}{target_w_line}\n"
        f"<b>Режим:</b> {MEAL_RU[profile.meal_regime]} · <b>Часовой пояс:</b> {profile.timezone}\n"
        f"<b>Ограничения:</b> {diet}, аллергии: {profile.allergies or 'нет'}\n\n"
        f"<b>Твой целевой калораж:</b> ~{kcal} ккал/день\n"
        f"<b>БЖУ:</b> {prot} / {fat} / {carb} г ({split[0]}% / {split[1]}% / {split[2]}%)\n\n"
        "Каждый вечер в 21:00 буду присылать отчёт по дню с учётом этой цели. Если что-то изменится — /settings.\n\n"
        "<b>Готов? Тогда начинаем — просто пришли фото еды!</b> 📸"
    )
    send = msg_or_cq.message.answer if isinstance(msg_or_cq, CallbackQuery) else msg_or_cq.answer
    await send(text, parse_mode="HTML", reply_markup=MAIN_KB)


# ── /start ─────────────────────────────────────────────────────────────────────
@router.message(Command("start"))
async def cmd_start(msg: Message) -> None:
    user = msg.from_user
    profile = await prof_repo.get_or_create(user.id, user.first_name, user.username)

    if profile.onboarding_status == "done":
        await msg.answer(
            "Ты уже прошёл знакомство 👍\nПросто пришли фото или нажми кнопку ниже.",
            reply_markup=MAIN_KB,
        )
        return

    if profile.onboarding_status == "in_progress" and profile.onboarding_step:
        await msg.answer("Продолжим знакомство 🙂")
        await _send_step(msg, profile.onboarding_step)
        return

    # pending — show disclaimer
    await msg.answer(
        "Привет! Я — твой нутри-помощник 🥗\n\n"
        "Прежде чем начнём, важное:\n\n"
        "Это <b>не медицинская консультация</b>. Для проблем со здоровьем — обратись к врачу. "
        "Бот не предназначен для лиц младше 18, беременных и кормящих.",
        parse_mode="HTML",
        reply_markup=KB_DISCLAIMER,
    )


# ── /restart ───────────────────────────────────────────────────────────────────
@router.message(Command("restart"))
async def cmd_restart(msg: Message) -> None:
    await prof_repo.reset_onboarding(msg.from_user.id)
    await msg.answer("Профиль сброшен. Начинаем заново 👋")
    await cmd_start(msg)


# ── disclaimer ─────────────────────────────────────────────────────────────────
@router.callback_query(F.data == "ob:disclaimer:accept")
async def cb_disclaimer(cq: CallbackQuery) -> None:
    await cq.answer()
    profile = await prof_repo.accept_disclaimer(cq.from_user.id)
    await cq.message.edit_reply_markup()
    await cq.message.answer(
        "Чтобы давать рекомендации, которые реально работают, мне нужно тебя узнать. "
        "Это ~2 минуты, 14 коротких вопросов 🙂"
    )
    await _send_step(cq, "q_sex")


# ── button answers ─────────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("ob:sex:"))
async def cb_sex(cq: CallbackQuery) -> None:
    val = cq.data.split(":")[2]
    profile = await prof_repo.update(cq.from_user.id, sex=val)
    await cq.answer()
    await cq.message.edit_reply_markup()
    await _next_step(cq, profile, "q_sex")


@router.callback_query(F.data.startswith("ob:body_type:"))
async def cb_body_type(cq: CallbackQuery) -> None:
    val = cq.data.split(":")[2]
    profile = await prof_repo.update(cq.from_user.id, body_type=val)
    await cq.answer()
    await cq.message.edit_reply_markup()
    await _next_step(cq, profile, "q_body_type")


@router.callback_query(F.data.startswith("ob:activity:"))
async def cb_activity(cq: CallbackQuery) -> None:
    val = cq.data.split(":")[2]
    profile = await prof_repo.update(cq.from_user.id, activity_level=val)
    await cq.answer()
    await cq.message.edit_reply_markup()
    await _next_step(cq, profile, "q_activity")


@router.callback_query(F.data.startswith("ob:goal:"))
async def cb_goal(cq: CallbackQuery) -> None:
    val = cq.data.split(":")[2]
    profile = await prof_repo.update(cq.from_user.id, goal=val)
    await cq.answer()
    await cq.message.edit_reply_markup()
    await _next_step(cq, profile, "q_goal")


@router.callback_query(F.data.startswith("ob:meal:"))
async def cb_meal(cq: CallbackQuery) -> None:
    val = cq.data.split(":")[2]
    profile = await prof_repo.update(cq.from_user.id, meal_regime=val)
    await cq.answer()
    await cq.message.edit_reply_markup()
    await _next_step(cq, profile, "q_meal_regime")


# ── diet multi-select ──────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("ob:diet:") & ~F.data.endswith(":done"))
async def cb_diet_toggle(cq: CallbackQuery) -> None:
    val = cq.data.split(":")[2]
    profile = await prof_repo.get(cq.from_user.id)
    selected: list[str] = list(profile.diet_restrictions or [])

    if val == "none":
        selected = ["none"] if "none" not in selected else []
    else:
        selected = [s for s in selected if s != "none"]
        if val in selected:
            selected.remove(val)
        else:
            selected.append(val)

    await prof_repo.update(cq.from_user.id, diet_restrictions=selected)
    await cq.answer()
    await cq.message.edit_reply_markup(reply_markup=diet_kb(selected))


@router.callback_query(F.data == "ob:diet:done")
async def cb_diet_done(cq: CallbackQuery) -> None:
    profile = await prof_repo.get(cq.from_user.id)
    selected = profile.diet_restrictions or []

    if "other" in selected:
        await prof_repo.update(cq.from_user.id, onboarding_step="q_diet_other")
        await cq.answer()
        await cq.message.edit_reply_markup()
        await cq.message.answer("Уточни, пожалуйста — какое именно ограничение?")
        return

    await cq.answer()
    await cq.message.edit_reply_markup()
    await _next_step(cq, profile, "q_diet_restrictions")


# ── text answers ───────────────────────────────────────────────────────────────
@router.message(F.text & ~F.text.startswith("/"), OnboardingNotDone())
async def text_answer(msg: Message, profile: Profile | None = None) -> None:
    if profile is None:
        profile = await prof_repo.get(msg.from_user.id)
    if not profile:
        return

    step = profile.onboarding_step
    if not step:
        return

    text = msg.text.strip()

    if step == "q_birth_year":
        try:
            year = int(text)
            assert 1925 <= year <= 2015
        except (ValueError, AssertionError):
            await msg.answer("Введи год числом от 1925 до 2015.")
            return
        profile = await prof_repo.update(msg.from_user.id, birth_year=year)
        await _next_step(msg, profile, step)

    elif step == "q_height":
        try:
            h = float(text.replace(",", "."))
            assert 100 <= h <= 230
        except (ValueError, AssertionError):
            await msg.answer("Введи рост от 100 до 230 см.")
            return
        profile = await prof_repo.update(msg.from_user.id, height_cm=h)
        await _next_step(msg, profile, step)

    elif step == "q_weight":
        try:
            w = float(text.replace(",", "."))
            assert 30 <= w <= 250
        except (ValueError, AssertionError):
            await msg.answer("Введи вес от 30 до 250 кг.")
            return
        profile = await prof_repo.update(msg.from_user.id, weight_kg=w)
        await _next_step(msg, profile, step)

    elif step == "q_target_weight":
        try:
            w = float(text.replace(",", "."))
            assert 30 <= w <= 250
        except (ValueError, AssertionError):
            await msg.answer("Введи вес от 30 до 250 кг.")
            return
        profile = await prof_repo.update(msg.from_user.id, target_weight_kg=w)
        await _next_step(msg, profile, step)

    elif step == "q_timezone":
        # fallback: geocode city name
        try:
            loop = asyncio.get_event_loop()
            location = await loop.run_in_executor(None, _geo.geocode, text)
            if not location:
                raise ValueError
            tz = _tf.timezone_at(lat=location.latitude, lng=location.longitude)
            if not tz:
                raise ValueError
        except Exception:
            await msg.answer("Не удалось определить часовой пояс по этому названию. Попробуй ещё раз или поделись геопозицией.")
            return
        profile = await prof_repo.update(msg.from_user.id, timezone=tz)
        await msg.answer(f"Определил: {tz} ✅", reply_markup=ReplyKeyboardRemove())
        await _next_step(msg, profile, step)

    elif step == "q_allergies":
        if not text:
            await msg.answer("Напиши хоть что-то, например «нет».")
            return
        profile = await prof_repo.update(msg.from_user.id, allergies=text)
        await _next_step(msg, profile, step)

    elif step == "q_diet_other":
        selected = list(profile.diet_restrictions or [])
        selected = [s for s in selected if s != "other"] + [f"other:{text}"]
        profile = await prof_repo.update(msg.from_user.id, diet_restrictions=selected, onboarding_step="q_foods_liked")
        await _send_step(msg, "q_foods_liked")

    elif step == "q_foods_liked":
        if not text:
            await msg.answer("Напиши хоть несколько продуктов.")
            return
        profile = await prof_repo.update(msg.from_user.id, foods_liked=text)
        await _next_step(msg, profile, step)

    elif step == "q_foods_disliked":
        if not text:
            await msg.answer("Напиши что-нибудь или «всё ок».")
            return
        profile = await prof_repo.update(msg.from_user.id, foods_disliked=text)
        await _finish(msg, profile)

    else:
        # any other step — user sent text during button step
        await msg.answer(f"Сначала закончим знакомство 🙂\n\n{_question(step, STEP_NUM.get(step, '?'))}", parse_mode="HTML", reply_markup=_kb(step))


# ── location answer ────────────────────────────────────────────────────────────
@router.message(F.location, OnboardingNotDone())
async def location_answer(msg: Message, profile: Profile | None = None) -> None:
    if profile is None:
        profile = await prof_repo.get(msg.from_user.id)
    if not profile:
        return

    if profile.onboarding_step != "q_timezone":
        await msg.answer("Геолокация сейчас не нужна.")
        return

    lat, lng = msg.location.latitude, msg.location.longitude
    tz = _tf.timezone_at(lat=lat, lng=lng)
    if not tz:
        await msg.answer("Не удалось определить часовой пояс по геолокации. Напиши название города.")
        return

    profile = await prof_repo.update(msg.from_user.id, timezone=tz)
    await msg.answer(f"Определил: {tz} ✅", reply_markup=ReplyKeyboardRemove())
    await _next_step(msg, profile, "q_timezone")
