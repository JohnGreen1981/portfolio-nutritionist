from __future__ import annotations

import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject


class ThrottlingMiddleware(BaseMiddleware):
    """Drop messages that arrive faster than min_interval seconds per user."""

    def __init__(self, min_interval: float = 1.5) -> None:
        self.min_interval = min_interval
        self._last: dict[int, float] = {}
        self._warned: set[int] = set()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message) or not event.from_user:
            return await handler(event, data)

        uid = event.from_user.id
        now = time.monotonic()
        delta = now - self._last.get(uid, 0.0)

        if delta < self.min_interval:
            if uid not in self._warned:
                self._warned.add(uid)
                await event.answer("⏳ Не так быстро — подожди секунду.")
            return

        self._warned.discard(uid)
        self._last[uid] = now
        return await handler(event, data)
