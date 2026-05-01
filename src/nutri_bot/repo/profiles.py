from __future__ import annotations

from datetime import datetime, timezone

from ..db import get_client
from ..schemas import Profile


async def get_or_create(telegram_id: int, first_name: str | None, username: str | None) -> Profile:
    client = get_client()
    res = await client.table("profiles").select("*").eq("telegram_id", telegram_id).limit(1).execute()
    if res.data:
        return Profile.model_validate(res.data[0])

    insert = {"telegram_id": telegram_id, "first_name": first_name, "username": username}
    res = await client.table("profiles").insert(insert).execute()
    return Profile.model_validate(res.data[0])


async def get(telegram_id: int) -> Profile | None:
    client = get_client()
    res = await client.table("profiles").select("*").eq("telegram_id", telegram_id).limit(1).execute()
    return Profile.model_validate(res.data[0]) if res.data else None


async def update(telegram_id: int, **fields) -> Profile:
    client = get_client()
    await client.table("profiles").update(fields).eq("telegram_id", telegram_id).execute()
    res = await client.table("profiles").select("*").eq("telegram_id", telegram_id).limit(1).execute()
    return Profile.model_validate(res.data[0])


async def accept_disclaimer(telegram_id: int) -> Profile:
    return await update(
        telegram_id,
        disclaimer_accepted_at=datetime.now(timezone.utc).isoformat(),
        onboarding_status="in_progress",
        onboarding_step="q_sex",
    )


async def finish_onboarding(telegram_id: int, target_kcal: int, target_prot_g: int, target_fat_g: int, target_carb_g: int) -> Profile:
    return await update(
        telegram_id,
        onboarding_status="done",
        onboarding_step=None,
        onboarded_at=datetime.now(timezone.utc).isoformat(),
        target_kcal=target_kcal,
        target_prot_g=target_prot_g,
        target_fat_g=target_fat_g,
        target_carb_g=target_carb_g,
    )


async def reset_onboarding(telegram_id: int) -> Profile:
    return await update(
        telegram_id,
        onboarding_status="pending",
        onboarding_step=None,
        disclaimer_accepted_at=None,
        onboarded_at=None,
        sex=None, birth_year=None, height_cm=None, weight_kg=None,
        body_type=None, activity_level=None, goal=None, target_weight_kg=None,
        meal_regime=None, timezone=None, allergies=None,
        diet_restrictions=[], foods_liked=None, foods_disliked=None,
        target_kcal=None, target_prot_g=None, target_fat_g=None, target_carb_g=None,
    )
