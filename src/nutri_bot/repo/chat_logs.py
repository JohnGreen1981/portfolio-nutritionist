from __future__ import annotations

from ..db import get_client


async def get_recent(chat_id: int, limit: int = 10) -> list[dict]:
    client = get_client()
    resp = (
        await client.table("chat_logs")
        .select("role,content")
        .eq("chat_id", chat_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return list(reversed(resp.data or []))


async def insert(
    chat_id: int,
    session_id: str,
    role: str,
    content: str,
    username: str | None = None,
    first_name: str | None = None,
) -> None:
    client = get_client()
    await client.table("chat_logs").insert({
        "chat_id": chat_id,
        "session_id": session_id,
        "role": role,
        "content": content,
        "username": username,
        "first_name": first_name,
    }).execute()
