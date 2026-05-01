from __future__ import annotations

import logging
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.filters import Filter
from aiogram.types import Message

from ..filters import OnboardingDone
from ..llm import transcribe_voice, parse_v, calc_macros
from ..repo import meals as meals_repo
from ..schemas import ParsedV, Profile
from .callbacks import _meal_card

log = logging.getLogger("nutri_bot.voice")
router = Router(name="voice")

# Users who pressed "🎙 Голос" — next voice message = food logging
_voice_food_mode: set[int] = set()


class VoiceFoodModeFilter(Filter):
    async def __call__(self, *args, **kwargs) -> bool:
        msg = args[0] if args else None
        if not hasattr(msg, "from_user") or not msg.from_user:
            return False
        return msg.from_user.id in _voice_food_mode


@router.message(F.text == "🎙 Голос", OnboardingDone())
async def btn_voice_mode(msg: Message, profile: Profile | None = None) -> None:
    _voice_food_mode.add(msg.from_user.id)
    await msg.answer("Запиши голосовое — скажи, что съел, и я залогирую 🎙")


@router.message(F.voice, OnboardingDone(), VoiceFoodModeFilter())
async def voice_food_handler(msg: Message, profile: Profile | None = None) -> None:
    _voice_food_mode.discard(msg.from_user.id)
    await msg.answer("Слушаю… 🎙")

    try:
        transcribed = await transcribe_voice(msg.bot, msg.voice.file_id)
    except Exception as exc:
        log.exception("Whisper error: %s", exc)
        await msg.answer("Не смог распознать голос 😕 Попробуй ещё раз или введи /v вручную.")
        return

    if not transcribed:
        await msg.answer("Ничего не расслышал 🤔 Попробуй ещё раз.")
        return

    log.debug("voice food transcribed: %s", transcribed)
    result = await parse_v(transcribed)
    if isinstance(result, str):
        await msg.answer(result, parse_mode="Markdown")
        return

    parsed: ParsedV = result
    if parsed.time:
        try:
            h, m = map(int, parsed.time.split(":"))
            now = datetime.now(timezone.utc)
            eaten_at = now.replace(hour=h, minute=m, second=0, microsecond=0)
        except Exception:
            eaten_at = datetime.now(timezone.utc)
    else:
        eaten_at = datetime.now(timezone.utc)

    try:
        macros = await calc_macros(parsed.dish, parsed.grams)
    except Exception as exc:
        log.exception("calc_macros error: %s", exc)
        await msg.answer("Не смог посчитать КБЖУ 😕 Попробуй ещё раз.")
        return

    meal = await meals_repo.insert_meal(
        chat_id=msg.from_user.id,
        dish=macros.dish,
        grams=parsed.grams,
        kcal=macros.kcal,
        prot=macros.prot,
        fat=macros.fat,
        carb=macros.carb,
        eaten_at=eaten_at,
    )

    text, kb = _meal_card(macros.dish, parsed.grams, macros.kcal, macros.prot, macros.fat, macros.carb, meal.id)
    await msg.answer(text, reply_markup=kb, parse_mode="HTML")
