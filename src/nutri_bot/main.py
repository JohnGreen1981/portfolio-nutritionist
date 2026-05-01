import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from .config import settings
from .db import create_db_client, close_client
from .middleware.onboarding_gate import OnboardingGate
from .middleware.throttling import ThrottlingMiddleware
from .handlers import onboarding as onboarding_router
from .handlers import photo as photo_router
from .handlers import callbacks as callbacks_router
from .handlers import manual as manual_router
from .handlers import settings as settings_router
from .handlers import today as today_router
from .handlers import chat as chat_router
from .scheduler import create_scheduler


def setup_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )


async def on_startup(bot: Bot) -> None:
    me = await bot.get_me()
    logging.getLogger("nutri_bot").info(
        "Bot started: @%s (id=%s)", me.username, me.id
    )


async def on_shutdown(bot: Bot) -> None:
    logging.getLogger("nutri_bot").info("Shutting down…")
    await close_client()
    await bot.session.close()


async def main() -> None:
    setup_logging()
    log = logging.getLogger("nutri_bot")

    await create_db_client(settings.supabase_url, settings.supabase_key)
    log.info("Supabase client created")

    bot = Bot(
        token=settings.tg_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    dp.message.outer_middleware(ThrottlingMiddleware(min_interval=1.5))
    dp.message.outer_middleware(OnboardingGate())
    dp.callback_query.outer_middleware(OnboardingGate())

    dp.include_router(onboarding_router.router)
    dp.include_router(callbacks_router.router)
    dp.include_router(photo_router.router)
    dp.include_router(manual_router.router)
    dp.include_router(settings_router.router)
    dp.include_router(today_router.router)
    dp.include_router(chat_router.router)  # must be last — fallback text handler

    scheduler = create_scheduler(bot)
    scheduler.start()
    log.info("Scheduler started — digest at 23:30 Europe/Belgrade")

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    log.info("Starting polling…")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    asyncio.run(main())
