from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from ..repo import profiles as prof_repo


class OnboardingGate(BaseMiddleware):
    """Injects 'profile' into handler data; blocks non-onboarding updates until done."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Message):
            user = event.from_user
        elif isinstance(event, CallbackQuery):
            user = event.from_user
        else:
            return await handler(event, data)

        if not user:
            return await handler(event, data)

        profile = await prof_repo.get(user.id)
        if profile is None:
            # new user — /start will create profile
            return await handler(event, data)

        data["profile"] = profile

        if profile.onboarding_status == "done":
            return await handler(event, data)

        # onboarding in progress — let onboarding router handle it
        # (onboarding router is registered first, so it takes priority)
        return await handler(event, data)
