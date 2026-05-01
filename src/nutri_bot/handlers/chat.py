from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.types import Message
from openai import AsyncOpenAI

from ..llm import transcribe_voice, calc_macros
from ..config import settings
from ..filters import OnboardingDone
from ..repo import chat_logs as logs_repo
from ..repo import digests as digests_repo
from ..repo import meals as meals_repo
from ..schemas import Profile
from .callbacks import _meal_card

log = logging.getLogger("nutri_bot.chat")
router = Router(name="chat")
_openai = AsyncOpenAI(api_key=settings.openai_api_key)

_GOAL_RU = {"lose": "Снижение веса", "maintain": "Удержание", "gain": "Набор массы"}
_ACTIVITY_RU = {
    "sedentary": "Сидячий", "light": "Лёгкий", "moderate": "Умеренный",
    "high": "Высокий", "very_high": "Очень высокий",
}
_MEAL_RU = {
    "3x": "3 раза в день", "4_5x": "4–5 раз",
    "intermittent": "Интервальное (16/8)", "irregular": "Нерегулярно",
}

_SYSTEM_TMPL = """\
Ты дипломированный нутрициолог. Отвечаешь на вопросы пользователя и консультируешь его. Веди себя профессионально, но общайся достаточно естественно — это мессенджер.

Сегодняшняя дата (по часовому поясу пользователя): {today_local}

Профиль пользователя:
- пол {sex}, возраст {age} лет, рост {height} см, вес {weight} кг
- цель: {goal_ru}{target_w}
- активность: {activity_ru}, режим питания: {meal_regime_ru}
- целевой kcal: {target_kcal}, БЖУ: {target_prot}/{target_fat}/{target_carb}
- ограничения: {diet_restrictions}
- аллергии: {allergies}
- любимые продукты: {foods_liked}; нелюбимые: {foods_disliked}

Приёмы пищи сегодня: {today_meals_text}

Вечерний отчёт за сегодня (если сформирован): {summary_md}

Инструменты:
- `log_meal(dish, grams, time?)` — ОБЯЗАТЕЛЬНО вызывай каждый раз, когда пользователь сообщает о съеденном или выпитом — явно («съел», «выпил», «перекусил») или косвенно («позавтракал», «был обед», «на завтрак была каша»). Если вес/объём не указан — оцени реалистичную порцию для данного продукта.
- `get_week_meals()` — вызывай при вопросах о прошлых днях или недельной динамике.
- Не давай медицинских советов; при симптомах рекомендуй обратиться к врачу.

Формат ответа: Telegram HTML.
- Жирный: <b>текст</b>
- Курсив: <i>текст</i>
- Никаких MarkdownV2 символов: не используй *, _, ~, `, [, ], (, ), #, >, +, -, =, |, {{, }}, ., ! со слэшем
- Эмодзи — активно, тематически (еда, тело, цифры). 1–3 на сообщение.
- Стиль: профессиональный нутрициолог + дружелюбный коуч, на «ты».\
"""

_LOG_MEAL_TOOL = {
    "type": "function",
    "function": {
        "name": "log_meal",
        "description": (
            "Сохраняет приём пищи в дневник питания. "
            "Вызывай каждый раз, когда пользователь упоминает что-то съеденное или выпитое — "
            "явно («съел», «выпил», «перекусил») или косвенно («позавтракал», «был обед», «на завтрак была каша»). "
            "Если вес не указан — оцени реалистичную порцию для данного продукта или блюда."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "dish": {
                    "type": "string",
                    "description": "Название блюда или продукта",
                },
                "grams": {
                    "type": "number",
                    "description": "Вес порции в граммах",
                },
                "time": {
                    "type": "string",
                    "description": "Время приёма пищи в формате HH:MM, если упомянуто пользователем",
                },
            },
            "required": ["dish", "grams"],
        },
    },
}

_WEEK_MEALS_TOOL = {
    "type": "function",
    "function": {
        "name": "get_week_meals",
        "description": "Возвращает приёмы пищи пользователя за последние 7 дней.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}


def _fmt_today_meals(meals, tz) -> str:
    if not meals:
        return "ничего не залогировано"
    lines = []
    total_kcal = 0.0
    for m in meals:
        t = m.eaten_at.astimezone(tz).strftime("%H:%M")
        lines.append(f"- {t} {m.dish} {int(m.grams)} г ({round(m.kcal)} ккал, Б{round(m.prot)}/Ж{round(m.fat)}/У{round(m.carb)})")
        total_kcal += m.kcal
    lines.append(f"Итого: {round(total_kcal)} ккал")
    return "\n".join(lines)


def _build_system(profile: Profile, summary_md: str | None, today_meals, tz) -> str:
    now_local = datetime.now(tz)
    age = now_local.year - profile.birth_year
    diet = ", ".join(profile.diet_restrictions) if profile.diet_restrictions else "нет"
    target_w = f" → {profile.target_weight_kg} кг" if profile.target_weight_kg else ""
    return _SYSTEM_TMPL.format(
        today_local=now_local.strftime("%Y-%m-%d"),
        sex="мужской" if profile.sex == "m" else "женский",
        age=age,
        height=int(profile.height_cm),
        weight=profile.weight_kg,
        goal_ru=_GOAL_RU.get(profile.goal, profile.goal),
        target_w=target_w,
        activity_ru=_ACTIVITY_RU.get(profile.activity_level, profile.activity_level),
        meal_regime_ru=_MEAL_RU.get(profile.meal_regime, profile.meal_regime),
        target_kcal=profile.target_kcal,
        target_prot=profile.target_prot_g,
        target_fat=profile.target_fat_g,
        target_carb=profile.target_carb_g,
        diet_restrictions=diet,
        allergies=profile.allergies or "нет",
        foods_liked=profile.foods_liked or "не указано",
        foods_disliked=profile.foods_disliked or "не указано",
        today_meals_text=_fmt_today_meals(today_meals, tz),
        summary_md=summary_md or "не сформирован",
    )


async def _exec_log_meal(
    tool_call_id: str,
    args: dict,
    profile: Profile,
    meal_cards: list[tuple],
) -> dict:
    dish = args["dish"]
    grams = float(args["grams"])
    time_str = args.get("time")

    if time_str:
        try:
            h, m_min = map(int, time_str.split(":"))
            eaten_at = datetime.now(timezone.utc).replace(hour=h, minute=m_min, second=0, microsecond=0)
        except Exception:
            eaten_at = datetime.now(timezone.utc)
    else:
        eaten_at = datetime.now(timezone.utc)

    try:
        macros = await calc_macros(dish, grams)
        meal = await meals_repo.insert_meal(
            chat_id=profile.telegram_id,
            dish=macros.dish,
            grams=grams,
            kcal=macros.kcal,
            prot=macros.prot,
            fat=macros.fat,
            carb=macros.carb,
            eaten_at=eaten_at,
        )
        meal_cards.append((macros.dish, grams, macros.kcal, macros.prot, macros.fat, macros.carb, meal.id))
        result = (
            f"Сохранено: {macros.dish}, {int(grams)} г, {round(macros.kcal)} ккал "
            f"(Б{round(macros.prot)}/Ж{round(macros.fat)}/У{round(macros.carb)})"
        )
    except Exception as exc:
        log.exception("log_meal tool error: %s", exc)
        result = "Ошибка при сохранении записи питания."

    return {"role": "tool", "tool_call_id": tool_call_id, "content": result}


async def _exec_get_week_meals(tool_call_id: str, profile: Profile, tz: ZoneInfo) -> dict:
    tz_name = profile.timezone or "Europe/Belgrade"
    meals = await meals_repo.get_week_meals(profile.telegram_id, tz_name)
    meals_data = [
        {
            "dish": m.dish, "grams": float(m.grams),
            "kcal": float(m.kcal), "prot": float(m.prot),
            "fat": float(m.fat), "carb": float(m.carb),
            "date_local": m.eaten_at.astimezone(tz).strftime("%Y-%m-%d"),
            "time_local": m.eaten_at.astimezone(tz).strftime("%H:%M"),
        }
        for m in meals
    ]
    return {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "content": json.dumps(meals_data, ensure_ascii=False),
    }


async def _call_agent(
    profile: Profile,
    user_text: str,
    summary_md: str | None,
    today_meals,
    tz: ZoneInfo,
    history: list[dict] | None = None,
) -> tuple[str, list[tuple]]:
    system = _build_system(profile, summary_md, today_meals, tz)
    messages: list[dict] = [{"role": "system", "content": system}]
    for row in (history or []):
        messages.append({"role": row["role"], "content": row["content"]})
    messages.append({"role": "user", "content": user_text})

    meal_cards: list[tuple] = []

    for _ in range(5):
        resp = await _openai.chat.completions.create(
            model="gpt-4.1",
            messages=messages,
            tools=[_LOG_MEAL_TOOL, _WEEK_MEALS_TOOL],
            tool_choice="auto",
            max_tokens=1024,
        )
        choice = resp.choices[0]

        if choice.finish_reason == "tool_calls":
            messages.append(choice.message)
            for tool_call in choice.message.tool_calls:
                fn = tool_call.function.name
                args = json.loads(tool_call.function.arguments)
                if fn == "log_meal":
                    result = await _exec_log_meal(tool_call.id, args, profile, meal_cards)
                elif fn == "get_week_meals":
                    result = await _exec_get_week_meals(tool_call.id, profile, tz)
                else:
                    result = {"role": "tool", "tool_call_id": tool_call.id, "content": "unknown tool"}
                messages.append(result)
            continue

        return choice.message.content or "", meal_cards

    return "Что-то пошло не так 😕 Попробуй ещё раз.", meal_cards


_HELP_TEXT = """\
<b>Как залогировать еду:</b>
📷 Фото — пришли фото, я распознаю все блюда на снимке
🗣 Голосовое — скажи что съел, я пойму и залогирую
✍️ Текст — напиши прямо в чат, например: <i>творог 200г</i>
/v блюдо граммы — ручной ввод командой

<b>Просмотр:</b>
📊 Сегодня — список приёмов пищи + КБЖУ + остаток до цели

<b>Управление:</b>
🗑 Удалить — выбрать запись дня для удаления
⚙️ Настройки — изменить вес, цель, активность и др.
/restart — пройти анкету заново

<b>Чат:</b>
Любой текст или голосовое — вопрос нутрициологу или запись о еде.
Я автоматически определю намерение и залогирую или отвечу 🥗\
"""


@router.message(F.text == "❓ Помощь", OnboardingDone())
async def cmd_help(msg: Message, profile: Profile | None = None) -> None:
    await msg.answer(_HELP_TEXT, parse_mode="HTML")


@router.message(F.voice, OnboardingDone())
async def voice_chat_handler(msg: Message, profile: Profile | None = None) -> None:
    try:
        transcribed = await transcribe_voice(msg.bot, msg.voice.file_id)
    except Exception as exc:
        log.exception("Whisper error in chat: %s", exc)
        await msg.answer("Не смог распознать голосовое 😕 Напиши текстом.")
        return

    if not transcribed:
        await msg.answer("Ничего не расслышал 🤔")
        return

    log.debug("voice chat transcribed: %s", transcribed)
    await _handle_chat(msg, profile, transcribed)


@router.message(F.text & ~F.text.startswith("/"), OnboardingDone())
async def chat_handler(msg: Message, profile: Profile | None = None) -> None:
    await _handle_chat(msg, profile, msg.text.strip())


async def _handle_chat(msg: Message, profile: Profile, user_text: str) -> None:
    session_id = date.today().isoformat()

    tz_name = profile.timezone or "Europe/Belgrade"
    tz = ZoneInfo(tz_name)
    today_local = datetime.now(tz).date()

    # Load history and today's data in parallel BEFORE inserting the current message
    history, today_meals_raw, digest_row = await asyncio.gather(
        logs_repo.get_recent(profile.telegram_id, limit=10),
        meals_repo.get_day_meals(profile.telegram_id, tz_name, today_local),
        digests_repo.get_today(profile.telegram_id, today_local),
    )
    summary_md = digest_row["summary_md"] if digest_row else None

    await logs_repo.insert(
        chat_id=profile.telegram_id,
        session_id=session_id,
        role="user",
        content=user_text,
        username=msg.from_user.username,
        first_name=msg.from_user.first_name,
    )

    thinking = await msg.answer("…")

    try:
        answer, meal_cards = await _call_agent(
            profile, user_text, summary_md, today_meals_raw, tz, history
        )
    except Exception as exc:
        log.exception("Chat agent error: %s", exc)
        await thinking.delete()
        await msg.answer("Что-то пошло не так 😕 Попробуй ещё раз.")
        return

    await thinking.delete()

    for card_data in meal_cards:
        text_card, kb = _meal_card(*card_data)
        await msg.answer(text_card, reply_markup=kb, parse_mode="HTML")

    if answer:
        try:
            await msg.answer(answer, parse_mode="HTML")
        except Exception as send_exc:
            log.warning("HTML send failed (%s), sending as plain text", send_exc)
            await msg.answer(answer)

    await logs_repo.insert(
        chat_id=profile.telegram_id,
        session_id=session_id,
        role="assistant",
        content=answer,
    )
