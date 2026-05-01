from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from ..db import get_client
from ..schemas import Candidate, MealDraft, MealRecord


# ── meals_draft ───────────────────────────────────────────────────────────────

async def create_draft(
    chat_id: int,
    message_id: int,
    photo_file_id: str,
    candidates: list[Candidate],
    grams_pred: float,
) -> MealDraft:
    client = get_client()
    data = {
        "chat_id": chat_id,
        "message_id": message_id,
        "photo_file_id": photo_file_id,
        "candidates": [c.model_dump() for c in candidates],
        "grams_pred": grams_pred,
        "status": "await_dish",
    }
    res = await client.table("meals_draft").insert(data).execute()
    return _parse_draft(res.data[0])


async def get_draft(chat_id: int, message_id: int) -> MealDraft | None:
    client = get_client()
    res = (
        await client.table("meals_draft")
        .select("*")
        .eq("chat_id", chat_id)
        .eq("message_id", message_id)
        .limit(1)
        .execute()
    )
    return _parse_draft(res.data[0]) if res.data else None


async def update_draft(chat_id: int, message_id: int, **fields) -> MealDraft:
    client = get_client()
    fields["updated_at"] = datetime.now(timezone.utc).isoformat()
    await client.table("meals_draft").update(fields).eq("chat_id", chat_id).eq("message_id", message_id).execute()
    res = await client.table("meals_draft").select("*").eq("chat_id", chat_id).eq("message_id", message_id).limit(1).execute()
    return _parse_draft(res.data[0])


def _parse_draft(row: dict) -> MealDraft:
    candidates = [Candidate.model_validate(c) for c in (row.get("candidates") or [])]
    return MealDraft(
        id=row["id"],
        chat_id=row["chat_id"],
        message_id=row["message_id"],
        photo_file_id=row.get("photo_file_id"),
        candidates=candidates,
        grams_pred=row.get("grams_pred"),
        chosen_name=row.get("chosen_name"),
        status=row.get("status", "await_dish"),
    )


# ── meals ─────────────────────────────────────────────────────────────────────

async def insert_meal(
    chat_id: int,
    dish: str,
    grams: float,
    kcal: float,
    prot: float,
    fat: float,
    carb: float,
    eaten_at: datetime,
) -> MealRecord:
    client = get_client()
    data = {
        "chat_id": chat_id,
        "dish": dish,
        "grams": grams,
        "kcal": kcal,
        "prot": prot,
        "fat": fat,
        "carb": carb,
        "eaten_at": eaten_at.isoformat(),
    }
    res = await client.table("meals").insert(data).execute()
    return MealRecord.model_validate(res.data[0])


async def get_meal(meal_id: int) -> MealRecord | None:
    client = get_client()
    res = await client.table("meals").select("*").eq("id", meal_id).limit(1).execute()
    return MealRecord.model_validate(res.data[0]) if res.data else None


async def soft_delete(meal_id: int) -> None:
    client = get_client()
    await client.table("meals").update({"deleted": True}).eq("id", meal_id).execute()


async def get_day_meals(chat_id: int, tz_name: str, for_date: date) -> list[MealRecord]:
    """Return non-deleted meals for a user on a given local date."""
    tz = ZoneInfo(tz_name)
    day_start = datetime(for_date.year, for_date.month, for_date.day, tzinfo=tz).astimezone(timezone.utc)
    day_end = day_start + timedelta(days=1)

    client = get_client()
    res = (
        await client.table("meals")
        .select("*")
        .eq("chat_id", chat_id)
        .eq("deleted", False)
        .gte("eaten_at", day_start.isoformat())
        .lt("eaten_at", day_end.isoformat())
        .order("eaten_at")
        .execute()
    )
    return [MealRecord.model_validate(r) for r in res.data]


async def get_week_meals(chat_id: int, tz_name: str) -> list[MealRecord]:
    """Return non-deleted meals for the last 7 local days."""
    tz = ZoneInfo(tz_name)
    today = datetime.now(tz).date()
    week_ago = today - timedelta(days=7)
    return await get_day_meals_range(chat_id, tz_name, week_ago, today)


async def get_day_meals_range(chat_id: int, tz_name: str, from_date: date, to_date: date) -> list[MealRecord]:
    tz = ZoneInfo(tz_name)
    start = datetime(from_date.year, from_date.month, from_date.day, tzinfo=tz).astimezone(timezone.utc)
    end = datetime(to_date.year, to_date.month, to_date.day, tzinfo=tz).astimezone(timezone.utc) + timedelta(days=1)

    client = get_client()
    res = (
        await client.table("meals")
        .select("*")
        .eq("chat_id", chat_id)
        .eq("deleted", False)
        .gte("eaten_at", start.isoformat())
        .lt("eaten_at", end.isoformat())
        .order("eaten_at")
        .execute()
    )
    return [MealRecord.model_validate(r) for r in res.data]
