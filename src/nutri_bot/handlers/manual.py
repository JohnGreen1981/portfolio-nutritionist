from __future__ import annotations

import logging
from datetime import datetime, timezone

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from ..llm import parse_v, calc_macros
from ..repo import meals as meals_repo
from ..schemas import ParsedV, Profile
from ..filters import OnboardingDone
from .callbacks import _meal_card

log = logging.getLogger("nutri_bot.manual")
router = Router(name="manual")


async def _process_food_text(msg: Message, text: str) -> None:
    result = await parse_v(text)
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

    text_card, kb = _meal_card(macros.dish, parsed.grams, macros.kcal, macros.prot, macros.fat, macros.carb, meal.id)
    await msg.answer(text_card, reply_markup=kb, parse_mode="HTML")


@router.message(Command("v"), OnboardingDone())
async def cmd_v(msg: Message, profile: Profile | None = None) -> None:
    args = msg.text.partition(" ")[2].strip()
    if not args:
        await msg.answer(
            "*Не распознал* 🤔\n\n"
            "*Формат:* /v блюдо граммы [HH:MM]\n"
            "*Пример:* /v яблоко 100г 18:00",
            parse_mode="Markdown",
        )
        return
    await _process_food_text(msg, args)
