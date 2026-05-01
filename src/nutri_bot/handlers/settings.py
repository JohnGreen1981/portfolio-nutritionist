from __future__ import annotations

import asyncio
import logging
from datetime import date

from aiogram import F, Router
from aiogram.filters import Command, Filter
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

from ..filters import OnboardingDone
from ..nutrition import calc_targets
from ..repo import profiles as prof_repo
from ..schemas import ACTIVITY_LABELS, GOAL_LABELS, MEAL_REGIME_LABELS, Profile

log = logging.getLogger("nutri_bot.settings")
router = Router(name="settings")
_tf = TimezoneFinder()
_geo = Nominatim(user_agent="nutri-bot-settings")

# uid → field currently being edited via text input
_editing: dict[int, str] = {}


class EditingSettingsFilter(Filter):
    async def __call__(self, *args, **kwargs) -> bool:
        msg = args[0] if args else None
        if not hasattr(msg, "from_user") or not msg.from_user:
            return False
        return msg.from_user.id in _editing


# ── helpers ───────────────────────────────────────────────────────────────────

def _ik(*rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=d) for t, d in row] for row in rows]
    )

_BACK_KB = _ik([("← К настройкам", "st:menu")])

KB_GOAL = _ik(
    [("📉 Снижение", "st:goal:lose"), ("⚖️ Удержание", "st:goal:maintain"), ("📈 Набор", "st:goal:gain")],
    [("← Отмена", "st:menu")],
)

KB_ACTIVITY = _ik(
    [("Сидячий", "st:activity:sedentary"), ("Лёгкий", "st:activity:light")],
    [("Умеренный", "st:activity:moderate")],
    [("Высокий", "st:activity:high"), ("Очень высокий", "st:activity:very_high")],
    [("← Отмена", "st:menu")],
)

KB_MEAL = _ik(
    [("3 раза в день", "st:meal:3x"), ("4–5 раз", "st:meal:4_5x")],
    [("Интервальное (16/8)", "st:meal:intermittent"), ("Нерегулярно", "st:meal:irregular")],
    [("← Отмена", "st:menu")],
)

KB_LOCATION = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="📍 Поделиться локацией", request_location=True)]],
    resize_keyboard=True,
    one_time_keyboard=True,
)

_DIET_OPTIONS = [
    ("Нет ограничений", "none"), ("Веган", "vegan"), ("Вегетарианец", "vegetarian"),
    ("Кето", "keto"), ("Без глютена", "gluten_free"), ("ПП", "pp"), ("Другое", "other"),
]


def _diet_kb(selected: list[str]) -> InlineKeyboardMarkup:
    rows = []
    for label, val in _DIET_OPTIONS:
        mark = "✅ " if val in selected else ""
        rows.append([InlineKeyboardButton(text=f"{mark}{label}", callback_data=f"st:diet:{val}")])
    rows.append([InlineKeyboardButton(text="Сохранить ✅", callback_data="st:diet:done")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _menu_text(profile: Profile) -> str:
    age = date.today().year - profile.birth_year
    goal_ru = GOAL_LABELS.get(profile.goal or "", profile.goal or "—")
    activity_ru = ACTIVITY_LABELS.get(profile.activity_level or "", profile.activity_level or "—")
    meal_ru = MEAL_REGIME_LABELS.get(profile.meal_regime or "", profile.meal_regime or "—")
    target_w = f" → {profile.target_weight_kg} кг" if profile.target_weight_kg else ""
    diet = ", ".join(profile.diet_restrictions) if profile.diet_restrictions else "нет"
    return (
        "⚙️ <b>Настройки профиля</b>\n\n"
        f"<b>Вес:</b> {profile.weight_kg} кг  •  <b>Рост:</b> {int(profile.height_cm)} см  •  <b>Возраст:</b> {age} лет\n"
        f"<b>Цель:</b> {goal_ru}{target_w}\n"
        f"<b>Активность:</b> {activity_ru}  •  <b>Режим питания:</b> {meal_ru}\n"
        f"<b>Часовой пояс:</b> {profile.timezone or 'не указан'}\n"
        f"<b>Ограничения:</b> {diet}\n"
        f"<b>Аллергии:</b> {profile.allergies or 'нет'}\n\n"
        f"<b>Целевой калораж:</b> {profile.target_kcal} ккал/день  •  "
        f"<b>БЖУ:</b> {profile.target_prot_g}/{profile.target_fat_g}/{profile.target_carb_g} г\n\n"
        "Что хочешь изменить?"
    )


def _menu_kb() -> InlineKeyboardMarkup:
    return _ik(
        [("⚖️ Вес", "st:field:weight"), ("🏁 Целевой вес", "st:field:target_weight")],
        [("🎯 Цель", "st:field:goal"), ("🏃 Активность", "st:field:activity")],
        [("🍽 Режим питания", "st:field:meal"), ("📍 Часовой пояс", "st:field:timezone")],
        [("🥗 Ограничения", "st:field:diet"), ("🌿 Аллергии", "st:field:allergies")],
        [("❤️ Люблю", "st:field:foods_liked"), ("🚫 Не люблю", "st:field:foods_disliked")],
    )


async def _recalculate(uid: int, profile: Profile) -> Profile:
    kcal, prot, fat, carb = calc_targets(profile)
    return await prof_repo.update(uid, target_kcal=kcal, target_prot_g=prot, target_fat_g=fat, target_carb_g=carb)


def _targets_line(profile: Profile) -> str:
    return (
        f"Новый целевой калораж: <b>{profile.target_kcal} ккал/день</b>\n"
        f"БЖУ: {profile.target_prot_g} / {profile.target_fat_g} / {profile.target_carb_g} г"
    )


# ── /settings ─────────────────────────────────────────────────────────────────

@router.message(F.text == "⚙️ Настройки", OnboardingDone())
@router.message(Command("settings"), OnboardingDone())
async def cmd_settings(msg: Message, profile: Profile | None = None) -> None:
    await msg.answer(_menu_text(profile), parse_mode="HTML", reply_markup=_menu_kb())


@router.callback_query(F.data == "st:menu", OnboardingDone())
async def cb_settings_menu(cq: CallbackQuery) -> None:
    _editing.pop(cq.from_user.id, None)
    profile = await prof_repo.get(cq.from_user.id)
    await cq.answer()
    try:
        await cq.message.edit_text(_menu_text(profile), parse_mode="HTML", reply_markup=_menu_kb())
    except Exception:
        await cq.message.answer(_menu_text(profile), parse_mode="HTML", reply_markup=_menu_kb())


# ── button-based fields ───────────────────────────────────────────────────────

@router.callback_query(F.data == "st:field:goal", OnboardingDone())
async def cb_field_goal(cq: CallbackQuery) -> None:
    await cq.answer()
    await cq.message.answer("Выбери цель:", reply_markup=KB_GOAL)


@router.callback_query(F.data.startswith("st:goal:"), OnboardingDone())
async def cb_set_goal(cq: CallbackQuery, profile: Profile | None = None) -> None:
    val = cq.data.split(":")[2]
    profile = await prof_repo.update(cq.from_user.id, goal=val)
    profile = await _recalculate(cq.from_user.id, profile)
    await cq.answer("Сохранено ✅")
    await cq.message.edit_text(
        f"Цель изменена: <b>{GOAL_LABELS[val]}</b>\n\n{_targets_line(profile)}",
        parse_mode="HTML",
        reply_markup=_BACK_KB,
    )


@router.callback_query(F.data == "st:field:activity", OnboardingDone())
async def cb_field_activity(cq: CallbackQuery) -> None:
    await cq.answer()
    await cq.message.answer("Выбери уровень активности:", reply_markup=KB_ACTIVITY)


@router.callback_query(F.data.startswith("st:activity:"), OnboardingDone())
async def cb_set_activity(cq: CallbackQuery, profile: Profile | None = None) -> None:
    val = cq.data.split(":")[2]
    profile = await prof_repo.update(cq.from_user.id, activity_level=val)
    profile = await _recalculate(cq.from_user.id, profile)
    await cq.answer("Сохранено ✅")
    await cq.message.edit_text(
        f"Активность изменена: <b>{ACTIVITY_LABELS[val]}</b>\n\n{_targets_line(profile)}",
        parse_mode="HTML",
        reply_markup=_BACK_KB,
    )


@router.callback_query(F.data == "st:field:meal", OnboardingDone())
async def cb_field_meal(cq: CallbackQuery) -> None:
    await cq.answer()
    await cq.message.answer("Выбери режим питания:", reply_markup=KB_MEAL)


@router.callback_query(F.data.startswith("st:meal:"), OnboardingDone())
async def cb_set_meal(cq: CallbackQuery) -> None:
    val = cq.data.split(":")[2]
    await prof_repo.update(cq.from_user.id, meal_regime=val)
    await cq.answer("Сохранено ✅")
    await cq.message.edit_text(
        f"Режим питания изменён: <b>{MEAL_REGIME_LABELS[val]}</b>",
        parse_mode="HTML",
        reply_markup=_BACK_KB,
    )


# ── diet multi-select ─────────────────────────────────────────────────────────

@router.callback_query(F.data == "st:field:diet", OnboardingDone())
async def cb_field_diet(cq: CallbackQuery, profile: Profile | None = None) -> None:
    await cq.answer()
    await cq.message.answer(
        "Выбери ограничения питания (можно несколько):",
        reply_markup=_diet_kb(list(profile.diet_restrictions or [])),
    )


@router.callback_query(F.data.startswith("st:diet:") & ~F.data.endswith(":done"), OnboardingDone())
async def cb_diet_toggle(cq: CallbackQuery, profile: Profile | None = None) -> None:
    val = cq.data.split(":")[2]
    selected = list(profile.diet_restrictions or [])
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
    await cq.message.edit_reply_markup(reply_markup=_diet_kb(selected))


@router.callback_query(F.data == "st:diet:done", OnboardingDone())
async def cb_diet_done(cq: CallbackQuery) -> None:
    profile = await prof_repo.get(cq.from_user.id)
    await cq.answer("Сохранено ✅")
    diet = ", ".join(profile.diet_restrictions) if profile.diet_restrictions else "нет"
    await cq.message.edit_text(
        f"Ограничения питания обновлены: <b>{diet}</b>",
        parse_mode="HTML",
        reply_markup=_BACK_KB,
    )


# ── text-based fields: prompt ─────────────────────────────────────────────────

_TEXT_PROMPTS: dict[str, str] = {
    "weight":        "Введи текущий вес в кг (например, 85.5):",
    "target_weight": "Введи целевой вес в кг (или «нет» чтобы убрать):",
    "allergies":     "Введи аллергии и непереносимости (или «нет»):",
    "foods_liked":   "Введи любимые продукты через запятую:",
    "foods_disliked":"Введи нелюбимые продукты (или «всё ок»):",
    "timezone":      "Поделись геопозицией или напиши название города:",
}

_TEXT_FIELDS = set(_TEXT_PROMPTS.keys())


@router.callback_query(
    F.data.in_({f"st:field:{f}" for f in _TEXT_FIELDS}),
    OnboardingDone(),
)
async def cb_field_text(cq: CallbackQuery) -> None:
    field = cq.data.split(":")[2]
    _editing[cq.from_user.id] = field
    await cq.answer()
    kb = KB_LOCATION if field == "timezone" else _ik([("← Отмена", "st:menu")])
    await cq.message.answer(_TEXT_PROMPTS[field], reply_markup=kb)


# ── text input handler ────────────────────────────────────────────────────────

@router.message(F.text & ~F.text.startswith("/"), OnboardingDone(), EditingSettingsFilter())
async def settings_text_input(msg: Message, profile: Profile | None = None) -> None:
    uid = msg.from_user.id
    field = _editing.pop(uid, None)
    if not field:
        return

    text = msg.text.strip()

    if field == "weight":
        try:
            w = float(text.replace(",", "."))
            assert 30 <= w <= 250
        except (ValueError, AssertionError):
            await msg.answer("Введи вес от 30 до 250 кг.")
            _editing[uid] = field
            return
        profile = await prof_repo.update(uid, weight_kg=w)
        profile = await _recalculate(uid, profile)
        await msg.answer(
            f"Вес обновлён: <b>{w} кг</b>\n\n{_targets_line(profile)}",
            parse_mode="HTML",
            reply_markup=_BACK_KB,
        )

    elif field == "target_weight":
        if text.lower() in ("нет", "убрать", "-"):
            await prof_repo.update(uid, target_weight_kg=None)
            await msg.answer("Целевой вес убран.", reply_markup=_BACK_KB)
        else:
            try:
                w = float(text.replace(",", "."))
                assert 30 <= w <= 250
            except (ValueError, AssertionError):
                await msg.answer("Введи вес от 30 до 250 кг (или «нет» чтобы убрать).")
                _editing[uid] = field
                return
            await prof_repo.update(uid, target_weight_kg=w)
            await msg.answer(
                f"Целевой вес обновлён: <b>{w} кг</b>",
                parse_mode="HTML",
                reply_markup=_BACK_KB,
            )

    elif field == "timezone":
        try:
            loop = asyncio.get_event_loop()
            location = await loop.run_in_executor(None, _geo.geocode, text)
            if not location:
                raise ValueError
            tz = _tf.timezone_at(lat=location.latitude, lng=location.longitude)
            if not tz:
                raise ValueError
        except Exception:
            await msg.answer(
                "Не удалось определить часовой пояс. Попробуй ещё раз или поделись геопозицией.",
                reply_markup=KB_LOCATION,
            )
            _editing[uid] = field
            return
        await prof_repo.update(uid, timezone=tz)
        await msg.answer(f"Определил: {tz} ✅", reply_markup=ReplyKeyboardRemove())
        await msg.answer(
            "Часовой пояс обновлён. Дайджест будет приходить в 21:00 по твоему времени.",
            reply_markup=_BACK_KB,
        )

    elif field == "allergies":
        if not text:
            await msg.answer("Напиши хоть что-то, например «нет».")
            _editing[uid] = field
            return
        await prof_repo.update(uid, allergies=text)
        await msg.answer(
            f"Аллергии обновлены: <b>{text}</b>",
            parse_mode="HTML",
            reply_markup=_BACK_KB,
        )

    elif field == "foods_liked":
        if not text:
            await msg.answer("Напиши хотя бы пару продуктов.")
            _editing[uid] = field
            return
        await prof_repo.update(uid, foods_liked=text)
        await msg.answer("Любимые продукты обновлены ✅", reply_markup=_BACK_KB)

    elif field == "foods_disliked":
        if not text:
            await msg.answer("Напиши что-нибудь или «всё ок».")
            _editing[uid] = field
            return
        await prof_repo.update(uid, foods_disliked=text)
        await msg.answer("Нелюбимые продукты обновлены ✅", reply_markup=_BACK_KB)


# ── location handler for timezone ─────────────────────────────────────────────

@router.message(F.location, OnboardingDone())
async def settings_location(msg: Message) -> None:
    uid = msg.from_user.id
    if _editing.get(uid) != "timezone":
        return
    _editing.pop(uid, None)

    tz = _tf.timezone_at(lat=msg.location.latitude, lng=msg.location.longitude)
    if not tz:
        await msg.answer("Не удалось определить часовой пояс. Напиши название города.")
        _editing[uid] = "timezone"
        return

    await prof_repo.update(uid, timezone=tz)
    await msg.answer(f"Определил: {tz} ✅", reply_markup=ReplyKeyboardRemove())
    await msg.answer(
        "Часовой пояс обновлён. Дайджест будет приходить в 21:00 по твоему времени.",
        reply_markup=_BACK_KB,
    )
