from datetime import datetime, date, time
from zoneinfo import ZoneInfo


def user_now(timezone: str) -> datetime:
    return datetime.now(tz=ZoneInfo(timezone))


def user_today(timezone: str) -> date:
    return user_now(timezone).date()


def user_local_time(timezone: str) -> time:
    return user_now(timezone).time()


def msk_now() -> datetime:
    return datetime.now(tz=ZoneInfo("Europe/Moscow"))


def msk_today() -> date:
    return msk_now().date()
