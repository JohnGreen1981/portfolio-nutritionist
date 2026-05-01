from __future__ import annotations

import base64
import io
import json
import logging

from aiogram import Bot
from openai import AsyncOpenAI

from .config import settings
from .schemas import Macros, ParsedV, Profile, VisionResult

log = logging.getLogger("nutri_bot.llm")
_openai = AsyncOpenAI(api_key=settings.openai_api_key)

# ── prompts ───────────────────────────────────────────────────────────────────

_VISION_SYSTEM = """\
Ты пищевой классификатор. Перечисли все позиции на фото.
Верни JSON ТОЛЬКО на русском, без ```:
{
  "items": [
    { "dish": "строка", "grams": число },
    ...
  ]
}
Правила:
- Составные блюда (салат, суп, рагу, каша) — ОДИН объект с названием блюда.
- Отдельные продукты рядом (яблоко и огурец, хлеб и сыр) — каждый своим объектом.
- Оценивай порцию реалистично. Максимум 5 объектов."""

_PARSER_SYSTEM = """\
Ты нутри-парсер.
Получаешь одну строку с описанием еды и время употребления.
- Если можешь разумно оценить порцию и массу (даже по словам типа «1 шт», «половина», «два куска») — верни ОДНУ строку JSON:
  {"dish":"…","grams":число[, "time":"HH:MM"]}
  time указывай только если нашёл в тексте, без даты.
- Если оценить нельзя — верни текст-подсказку:
  *Не распознал* 🤔
  *Формат:* /v блюдо граммы [HH:MM]
  *Пример:* /v яблоко 100г 18:00"""

_NUTRI_SYSTEM = """\
Ты нутри-калькулятор.
На вход получаешь JSON { "dish":"строка", "grams":число }.
Отвечай строго JSON одной строкой:
{ "dish":"строка", "kcal":число, "prot":число, "fat":число, "carb":число }
Без пояснений, без ```."""


# ── public API ────────────────────────────────────────────────────────────────

async def vision(bot: Bot, file_id: str) -> VisionResult:
    """Identify dish from photo using GPT-4o vision."""
    tg_file = await bot.get_file(file_id)
    buf = io.BytesIO()
    await bot.download_file(tg_file.file_path, destination=buf)
    b64 = base64.b64encode(buf.getvalue()).decode()

    resp = await _openai.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": _VISION_SYSTEM},
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
            ]},
        ],
        response_format={"type": "json_object"},
        max_tokens=512,
    )
    raw = resp.choices[0].message.content
    log.debug("vision raw: %s", raw)
    return VisionResult.model_validate_json(raw)


async def parse_v(text: str) -> ParsedV | str:
    """Parse /v command text. Returns ParsedV on success, hint string on failure."""
    resp = await _openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": _PARSER_SYSTEM},
            {"role": "user", "content": text},
        ],
        max_tokens=128,
    )
    raw = resp.choices[0].message.content.strip()
    log.debug("parser raw: %s", raw)
    try:
        data = json.loads(raw)
        return ParsedV.model_validate(data)
    except Exception:
        return raw  # hint text


_DIGEST_SYSTEM_TMPL = """\
Ты нутри-диетолог-бот. На вход приходит отчёт о питании пользователя за день в JSON, плюс его профиль и цели.

Профиль: пол {sex}, возраст {age} лет, рост {height} см, вес {weight} кг.
Цель: {goal_en} ({goal_ru}). Целевой kcal: {target_kcal}, БЖУ: {target_prot}/{target_fat}/{target_carb}.
Ограничения: {diet_restrictions}, аллергии: {allergies}.

Сделай отчёт:
• Итог КБЖУ за день: kcal, Б, Ж, У
• Сравнение с целью (одна строка)
• Замечания (кратко, только если есть, что заметить по структуре дня)
• Совет на завтра: 1 конкретная рекомендация

В конце: «Если будут вопросы — пиши :)»

Тон: гибрид профессионального нутрициолога и дружелюбного коуча. Сохраняй цифры, смягчай формулировки, без сюсюкания. На «ты», 1–2 эмодзи на сообщение.
Формат: Telegram Markdown legacy. Жирный — одна `*`, курсив — одна `_`. Не выдавай ``` и не возвращай JSON.\
"""

_GOAL_RU = {"lose": "Снижение веса", "maintain": "Удержание", "gain": "Набор массы"}


async def build_digest(profile: Profile, meals_json: list[dict]) -> str:
    """Generate evening digest text for a user."""
    from datetime import date as _date
    age = _date.today().year - profile.birth_year
    diet = ", ".join(profile.diet_restrictions) if profile.diet_restrictions else "нет"

    system = _DIGEST_SYSTEM_TMPL.format(
        sex="мужской" if profile.sex == "m" else "женский",
        age=age,
        height=int(profile.height_cm),
        weight=profile.weight_kg,
        goal_en=profile.goal,
        goal_ru=_GOAL_RU.get(profile.goal, profile.goal),
        target_kcal=profile.target_kcal,
        target_prot=profile.target_prot_g,
        target_fat=profile.target_fat_g,
        target_carb=profile.target_carb_g,
        diet_restrictions=diet,
        allergies=profile.allergies or "нет",
    )

    import json as _json
    user_content = _json.dumps(meals_json, ensure_ascii=False)

    resp = await _openai.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
        max_tokens=1024,
    )
    return resp.choices[0].message.content.strip()


async def transcribe_voice(bot: Bot, file_id: str) -> str:
    """Transcribe a Telegram voice/audio file using OpenAI Whisper."""
    tg_file = await bot.get_file(file_id)
    buf = io.BytesIO()
    await bot.download_file(tg_file.file_path, destination=buf)
    buf.seek(0)
    buf.name = "voice.ogg"
    response = await _openai.audio.transcriptions.create(
        model="whisper-1",
        file=buf,
        language="ru",
    )
    log.debug("whisper raw: %s", response.text)
    return response.text or ""


async def calc_macros(dish: str, grams: float) -> Macros:
    """Calculate КБЖУ for a dish/grams pair."""
    payload = json.dumps({"dish": dish, "grams": grams}, ensure_ascii=False)
    resp = await _openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": _NUTRI_SYSTEM},
            {"role": "user", "content": payload},
        ],
        response_format={"type": "json_object"},
        max_tokens=128,
    )
    raw = resp.choices[0].message.content
    log.debug("nutri raw: %s", raw)
    return Macros.model_validate_json(raw)
