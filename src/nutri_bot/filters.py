import logging
from aiogram.filters import Filter

from .schemas import Profile

log = logging.getLogger("nutri_bot.filters")


class OnboardingDone(Filter):
    async def __call__(self, *_, profile: Profile | None = None) -> bool:
        result = profile is not None and profile.onboarding_status == "done"
        log.debug("OnboardingDone: status=%s → %s", profile and profile.onboarding_status, result)
        return result


class OnboardingNotDone(Filter):
    async def __call__(self, *_, profile: Profile | None = None) -> bool:
        result = profile is None or profile.onboarding_status != "done"
        log.debug("OnboardingNotDone: status=%s → %s", profile and profile.onboarding_status, result)
        return result
