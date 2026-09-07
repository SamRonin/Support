"""Entry point: mother bot polling + child bots supervisor."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from . import config, db
from . import ai_client
from .child import manager
from .middlewares import ThrottleMiddleware, UserMiddleware
from .mother import admin, create_bot, fallback, purchase, referral, settings, start, support

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
logging.getLogger("aiogram.event").setLevel(logging.WARNING)
log = logging.getLogger("main")


def build_mother_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(start.router)
    dp.include_router(create_bot.router)
    dp.include_router(settings.router)
    dp.include_router(purchase.router)
    dp.include_router(referral.router)
    dp.include_router(support.router)
    dp.include_router(admin.router)
    # fallback LAST: catches texts that no dialog matched (expired dialogs etc.)
    dp.include_router(fallback.router)

    # register middlewares for all update types
    for observer in (dp.message, dp.callback_query):
        observer.middleware(UserMiddleware())
        observer.middleware(ThrottleMiddleware())
    return dp


async def main() -> None:
    if not config.BOT_TOKEN:
        raise SystemExit("MOTHER_BOT_TOKEN is not set! Check .env / Railway variables.")
    if not config.DATABASE_URL:
        raise SystemExit("DATABASE_URL is not set! Check .env / Railway variables.")

    await db.init_pool()

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = build_mother_dispatcher()

    # start all registered child bots
    await manager.start_all()

    log.info("Mother bot starting (polling)...")
    try:
        await dp.start_polling(
            bot,
            allowed_updates=["message", "callback_query", "web_app_data"],
        )
    finally:
        log.info("Shutting down: stopping child bots...")
        await manager.stop_all()
        await ai_client.close_client()
        await db.close_pool()
        try:
            await bot.session.close()
        except Exception:
            pass
        log.info("Bye.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit) as e:
        if isinstance(e, SystemExit) and e.code:
            raise
