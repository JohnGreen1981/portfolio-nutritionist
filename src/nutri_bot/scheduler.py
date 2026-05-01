from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone as dt_tz
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .llm import build_digest
from .db import get_client
from .repo import digests as digests_repo
from .repo import meals as meals_repo
from .repo import profiles as prof_repo
from .schemas import Profile

log = logging.getLogger("nutri_bot.scheduler")

DIGEST_TZ = ZoneInfo("Europe/Belgrade")
DIGEST_HOUR = 23
DIGEST_MINUTE = 30

NUDGE_HOUR = 9
NUDGE_MINUTE = 0
NUDGE_INTERVAL_DAYS = 14

_NUDGE_TEXT = (
    "Привет! Прошло 2 недели — самое время взвеситься 📊\n\n"
    "Обнови вес, чтобы я пересчитал калораж под твои текущие данные."
)
_NUDGE_KB = InlineKeyboardMarkup(inline_keyboard=[[
    InlineKeyboardButton(text="✏️ Ввести новый вес", callback_data="st:field:weight"),
]])

_EMPTY_DIGEST = (
    "Сегодня ничего не залогировано — попробуй фото или /v 🙂\n\n"
    "Если будут вопросы — пиши :)"
)


async def _send_digest(bot: Bot) -> None:
    now_bel = datetime.now(DIGEST_TZ)
    today = now_bel.date()
    log.info("Digest job started for %s", today)

    # load all onboarded users
    client = get_client()
    res = await client.table("profiles").select("*").eq("onboarding_status", "done").execute()
    profiles = [Profile.model_validate(r) for r in res.data]

    for profile in profiles:
        try:
            await _process_user(bot, profile, today)
        except Exception:
            log.exception("Digest failed for telegram_id=%s", profile.telegram_id)


async def _process_user(bot: Bot, profile: Profile, today) -> None:
    # idempotency: skip if already sent today
    existing = await digests_repo.get_today(profile.telegram_id, today)
    if existing:
        return

    tz_name = profile.timezone or "Europe/Belgrade"
    meals = await meals_repo.get_day_meals(profile.telegram_id, tz_name, today)

    if not meals:
        sent = await bot.send_message(profile.telegram_id, _EMPTY_DIGEST)
        await digests_repo.upsert(
            chat_id=profile.telegram_id,
            for_date=today,
            kcal=0, prot=0, fat=0, carb=0,
            meals_json=[],
            summary_md=_EMPTY_DIGEST,
            msg_id=sent.message_id,
        )
        return

    total_kcal = sum(m.kcal for m in meals)
    total_prot = sum(m.prot for m in meals)
    total_fat  = sum(m.fat  for m in meals)
    total_carb = sum(m.carb for m in meals)

    meals_json = [
        {
            "dish": m.dish,
            "grams": float(m.grams),
            "kcal": float(m.kcal),
            "prot": float(m.prot),
            "fat":  float(m.fat),
            "carb": float(m.carb),
            "eaten_at": m.eaten_at.isoformat(),
        }
        for m in meals
    ]

    summary = await build_digest(profile, meals_json)
    sent = await bot.send_message(profile.telegram_id, summary, parse_mode="Markdown")

    await digests_repo.upsert(
        chat_id=profile.telegram_id,
        for_date=today,
        kcal=total_kcal,
        prot=total_prot,
        fat=total_fat,
        carb=total_carb,
        meals_json=meals_json,
        summary_md=summary,
        msg_id=sent.message_id,
    )
    log.info("Digest sent to telegram_id=%s (%d meals, %.0f kcal)", profile.telegram_id, len(meals), total_kcal)


async def _send_nudge(bot: Bot) -> None:
    now = datetime.now(dt_tz.utc)
    log.info("Nudge job started at %s", now.isoformat())

    client = get_client()
    res = await client.table("profiles").select("*").eq("onboarding_status", "done").execute()
    profiles = [Profile.model_validate(r) for r in res.data]

    for profile in profiles:
        try:
            last = profile.last_weight_nudge_at
            if last is not None and (now - last) < timedelta(days=NUDGE_INTERVAL_DAYS):
                continue
            await bot.send_message(profile.telegram_id, _NUDGE_TEXT, reply_markup=_NUDGE_KB)
            await prof_repo.update(profile.telegram_id, last_weight_nudge_at=now.isoformat())
            log.info("Nudge sent to telegram_id=%s", profile.telegram_id)
        except Exception:
            log.exception("Nudge failed for telegram_id=%s", profile.telegram_id)


def create_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=DIGEST_TZ)
    scheduler.add_job(
        _send_digest,
        trigger=CronTrigger(hour=DIGEST_HOUR, minute=DIGEST_MINUTE, timezone=DIGEST_TZ),
        args=[bot],
        id="evening_digest",
        replace_existing=True,
    )
    scheduler.add_job(
        _send_nudge,
        trigger=CronTrigger(hour=NUDGE_HOUR, minute=NUDGE_MINUTE, timezone=DIGEST_TZ),
        args=[bot],
        id="weight_nudge",
        replace_existing=True,
    )
    return scheduler
