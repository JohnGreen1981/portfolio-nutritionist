from __future__ import annotations

import logging
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from ..llm import calc_macros
from ..repo import meals as meals_repo
from ..schemas import Profile

log = logging.getLogger("nutri_bot.callbacks")
router = Router(name="callbacks")


def _weight_kb(grams: float, message_id: int) -> InlineKeyboardMarkup:
    g = round(grams)
    step = 25 if g < 150 else 50
    opts = [g - 2 * step, g - step, g, g + step, g + 2 * step, g + 3 * step]
    opts = [o for o in opts if o > 0][:6]
    rows = [
        [InlineKeyboardButton(text=f"{o} г", callback_data=f"weight_{o}_{message_id}") for o in opts[:3]],
        [InlineKeyboardButton(text=f"{o} г", callback_data=f"weight_{o}_{message_id}") for o in opts[3:]],
    ]
    return InlineKeyboardMarkup(inline_keyboard=[r for r in rows if r])


def _meal_card(dish: str, grams: float, kcal: float, prot: float, fat: float, carb: float, meal_id: int, saved: bool = True) -> tuple[str, InlineKeyboardMarkup]:
    if saved:
        status_line = "✔️ <i>сохранил в память</i>"
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🚫 не сохранять", callback_data=f"cancel_{meal_id}")
        ]])
    else:
        status_line = "🚫 <i>не сохранил</i>"
        kb = InlineKeyboardMarkup(inline_keyboard=[])

    text = (
        f"<b>{dish} – {int(grams)} г</b>\n\n"
        f"<b>Калорий:</b> {round(kcal)}\n"
        f"<b>Б:</b> {round(prot)}  <b>Ж:</b> {round(fat)}  <b>У:</b> {round(carb)}\n\n"
        f"{status_line}"
    )
    return text, kb


# ── dish_yes ───────────────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("dish_yes_"))
async def cb_dish_yes(cq: CallbackQuery) -> None:
    message_id = int(cq.data.split("dish_yes_")[1])
    draft = await meals_repo.get_draft(cq.from_user.id, message_id)
    if not draft or not draft.candidates:
        await cq.answer("Сессия устарела, пришли фото ещё раз.")
        return

    top = draft.candidates[0]
    await meals_repo.update_draft(
        cq.from_user.id, message_id,
        status="await_weight",
        chosen_name=top.dish,
    )
    await cq.answer()
    await cq.message.edit_reply_markup(reply_markup=_weight_kb(top.grams, message_id))
    await cq.message.edit_text(
        f"<b>{top.dish}</b> — сколько граммов?",
        reply_markup=_weight_kb(top.grams, message_id),
        parse_mode="HTML",
    )


# ── dish_no ────────────────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("dish_no_"))
async def cb_dish_no(cq: CallbackQuery) -> None:
    message_id = int(cq.data.split("dish_no_")[1])
    await meals_repo.update_draft(cq.from_user.id, message_id, status="cancelled")
    await cq.answer()
    await cq.message.edit_text(
        "Понял. Введи правильное название через /v блюдо граммы",
        reply_markup=None,
    )


# ── weight ─────────────────────────────────────────────────────────────────────
@router.callback_query(F.data.regexp(r"^weight_\d+_\d+$"))
async def cb_weight(cq: CallbackQuery) -> None:
    parts = cq.data.split("_")
    grams = float(parts[1])
    message_id = int(parts[2])

    draft = await meals_repo.get_draft(cq.from_user.id, message_id)
    if not draft or not draft.chosen_name:
        await cq.answer("Сессия устарела.")
        return

    await cq.answer("Считаю КБЖУ…")

    try:
        macros = await calc_macros(draft.chosen_name, grams)
    except Exception as exc:
        log.exception("calc_macros error: %s", exc)
        await cq.message.edit_text("Не смог посчитать КБЖУ 😕 Попробуй ещё раз.")
        return

    meal = await meals_repo.insert_meal(
        chat_id=cq.from_user.id,
        dish=macros.dish,
        grams=grams,
        kcal=macros.kcal,
        prot=macros.prot,
        fat=macros.fat,
        carb=macros.carb,
        eaten_at=datetime.now(timezone.utc),
    )
    await meals_repo.update_draft(cq.from_user.id, message_id, status="done")

    text, kb = _meal_card(macros.dish, grams, macros.kcal, macros.prot, macros.fat, macros.carb, meal.id)
    await cq.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


# ── del:meal ──────────────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("del:meal:"))
async def cb_del_meal(cq: CallbackQuery, profile: Profile | None = None) -> None:
    meal_id = int(cq.data.split("del:meal:")[1])
    await meals_repo.soft_delete(meal_id)
    await cq.answer("Удалено ✓")
    await cq.message.delete()


# ── del:cancel ────────────────────────────────────────────────────────────────
@router.callback_query(F.data == "del:cancel")
async def cb_del_cancel(cq: CallbackQuery) -> None:
    await cq.answer("Отмена")
    await cq.message.delete()


# ── cancel ─────────────────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("cancel_"))
async def cb_cancel(cq: CallbackQuery) -> None:
    meal_id = int(cq.data.split("cancel_")[1])
    meal = await meals_repo.get_meal(meal_id)
    await meals_repo.soft_delete(meal_id)
    await cq.answer("Удалил из памяти.")

    if meal:
        text, _ = _meal_card(meal.dish, meal.grams, meal.kcal, meal.prot, meal.fat, meal.carb, meal_id, saved=False)
    else:
        text = "🚫 <i>не сохранил</i>"

    await cq.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[]),
        parse_mode="HTML",
    )
