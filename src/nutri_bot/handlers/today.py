from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from ..repo import meals as meals_repo
from ..schemas import Profile
from ..filters import OnboardingDone

log = logging.getLogger("nutri_bot.today")
router = Router(name="today")


def _format_today(meals, profile: Profile) -> str:
    if not meals:
        return "Сегодня ещё ничего не залогировано 📭\nПришли фото, голосовое или напиши что съел."

    total_kcal = sum(m.kcal for m in meals)
    total_prot = sum(m.prot for m in meals)
    total_fat = sum(m.fat for m in meals)
    total_carb = sum(m.carb for m in meals)

    tz = ZoneInfo(profile.timezone or "Europe/Belgrade")
    lines = ["<b>Сегодня:</b>\n"]
    for m in meals:
        eaten_local = m.eaten_at.astimezone(tz)
        lines.append(f"  {eaten_local.strftime('%H:%M')} — {m.dish} {int(m.grams)} г  ({round(m.kcal)} ккал)")

    lines.append(
        f"\n<b>Итого:</b> {round(total_kcal)} ккал  "
        f"Б {round(total_prot)} / Ж {round(total_fat)} / У {round(total_carb)}"
    )
    if profile.target_kcal:
        remaining = profile.target_kcal - total_kcal
        arrow = "осталось" if remaining >= 0 else "перебор"
        lines.append(f"<b>До цели:</b> {abs(round(remaining))} ккал {arrow}")

    return "\n".join(lines)


@router.message(F.text == "📊 Сегодня", OnboardingDone())
@router.message(Command("today"), OnboardingDone())
async def cmd_today(msg: Message, profile: Profile | None = None) -> None:
    tz_name = profile.timezone or "Europe/Belgrade"
    today = datetime.now(ZoneInfo(tz_name)).date()
    meals = await meals_repo.get_day_meals(msg.from_user.id, tz_name, today)
    await msg.answer(_format_today(meals, profile), parse_mode="HTML")


@router.message(F.text == "🗑 Удалить", OnboardingDone())
@router.message(Command("delete"), OnboardingDone())
async def cmd_delete(msg: Message, profile: Profile | None = None) -> None:
    tz_name = profile.timezone or "Europe/Belgrade"
    today = datetime.now(ZoneInfo(tz_name)).date()
    meals = await meals_repo.get_day_meals(msg.from_user.id, tz_name, today)

    if not meals:
        await msg.answer("Сегодня нет записей для удаления.")
        return

    tz = ZoneInfo(tz_name)
    buttons = []
    for m in meals:
        t = m.eaten_at.astimezone(tz).strftime("%H:%M")
        label = f"{t} {m.dish} {int(m.grams)} г"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"del:meal:{m.id}")])

    buttons.append([InlineKeyboardButton(text="Отмена", callback_data="del:cancel")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await msg.answer("<b>Что удалить?</b>", reply_markup=kb, parse_mode="HTML")
