from __future__ import annotations

import logging
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from ..llm import vision
from ..repo import meals as meals_repo
from ..schemas import Candidate, Profile
from ..filters import OnboardingDone

log = logging.getLogger("nutri_bot.photo")
router = Router(name="photo")


def _weight_kb(grams: float, message_id: int) -> InlineKeyboardMarkup:
    g = round(grams)
    step = 20 if g < 120 else 50
    options = [g - step, g, g + step]
    options = [o for o in options if o > 0]
    buttons = [
        InlineKeyboardButton(text=f"{o} г", callback_data=f"weight_{o}_{message_id}")
        for o in options
    ]
    return InlineKeyboardMarkup(inline_keyboard=[buttons])


@router.message(F.photo, OnboardingDone())
async def photo_handler(msg: Message, profile: Profile | None = None) -> None:

    await msg.answer("Смотрю, что на фото… 🔍")

    file_id = msg.photo[-1].file_id
    try:
        vision_result = await vision(msg.bot, file_id)
    except Exception as exc:
        log.exception("Vision API error: %s", exc)
        await msg.answer("Не смог распознать фото 😕 Попробуй ещё раз или введи /v вручную.")
        return

    if not vision_result.items:
        await msg.answer("Не смог распознать блюдо на фото 😕 Попробуй /v вручную.")
        return

    for item in vision_result.items:
        # Send question first to get the bot message_id (used as draft key)
        sent = await msg.answer(
            f"Это <b>{item.dish}</b>?",
            parse_mode="HTML",
        )
        item_msg_id = sent.message_id

        await meals_repo.create_draft(
            chat_id=msg.from_user.id,
            message_id=item_msg_id,
            photo_file_id=file_id,
            candidates=[Candidate(dish=item.dish, grams=item.grams, confidence=1.0)],
            grams_pred=item.grams,
        )

        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Да", callback_data=f"dish_yes_{item_msg_id}"),
            InlineKeyboardButton(text="❌ Нет", callback_data=f"dish_no_{item_msg_id}"),
        ]])
        await sent.edit_reply_markup(reply_markup=kb)
