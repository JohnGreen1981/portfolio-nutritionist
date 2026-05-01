from __future__ import annotations

from datetime import date, datetime, timezone

from ..db import get_client


async def get_today(chat_id: int, for_date: date) -> dict | None:
    client = get_client()
    res = (
        await client.table("digests")
        .select("*")
        .eq("chat_id", chat_id)
        .eq("for_date", for_date.isoformat())
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


async def upsert(
    chat_id: int,
    for_date: date,
    kcal: float,
    prot: float,
    fat: float,
    carb: float,
    meals_json: list[dict],
    summary_md: str,
    msg_id: int | None = None,
) -> dict:
    client = get_client()
    data = {
        "chat_id": chat_id,
        "for_date": for_date.isoformat(),
        "kcal": kcal,
        "prot": prot,
        "fat": fat,
        "carb": carb,
        "meals_json": meals_json,
        "summary_md": summary_md,
        "msg_id": msg_id,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await client.table("digests").upsert(data, on_conflict="chat_id,for_date").execute()
    res = (
        await client.table("digests")
        .select("*")
        .eq("chat_id", chat_id)
        .eq("for_date", for_date.isoformat())
        .limit(1)
        .execute()
    )
    return res.data[0]
