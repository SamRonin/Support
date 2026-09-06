"""Child bot supervisor: runs a polling task per registered child bot.

Child handlers live in `child/handlers.py` and are reused for every bot.
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher

from .. import repo
from . import handlers

log = logging.getLogger("child.manager")

_tasks: dict[int, asyncio.Task] = {}


def _build_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    dp.include_router(handlers.router)
    return dp


async def _poll_loop(bot_id: int, token: str) -> None:
    dp = _build_dispatcher()
    bot = Bot(token=token)
    try:
        await bot.delete_webhook(drop_pending_updates=False)
        log.info("Child bot #%d (@%s) polling started", bot_id, bot.username if hasattr(bot, "username") else "?")
        await dp.start_polling(
            bot,
            handle_signals=False,
            allowed_updates=["message", "callback_query", "business_message", "business_connection"],
        )
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.error("Child bot #%d crashed: %r", bot_id, e)
        count = await repo.bump_error_count(bot_id)
        if count >= 10:
            await repo.set_bot_active(bot_id, False)
            log.error("Child bot #%d disabled after repeated errors", bot_id)
    finally:
        try:
            await bot.session.close()
        except Exception:
            pass
        _tasks.pop(bot_id, None)


def start_bot_task(bot_id: int) -> asyncio.Task:
    """(Re)start the polling task for a bot; returns the task."""
    stop_bot_task(bot_id)

    async def _runner() -> None:
        row = await repo.get_bot(bot_id)
        if not row or not row["active"]:
            return
        await _poll_loop(bot_id, row["token"])

    task = asyncio.create_task(_runner(), name=f"child-bot-{bot_id}")
    _tasks[bot_id] = task
    return task


def stop_bot_task(bot_id: int) -> None:
    task = _tasks.pop(bot_id, None)
    if task and not task.done():
        task.cancel()


def running_bot_ids() -> set[int]:
    alive = set()
    for bid, task in _tasks.items():
        if not task.done():
            alive.add(bid)
    return alive


async def start_all() -> None:
    """Launch all active bots on startup (refresh pro flags first)."""
    await repo.refresh_pro_flags()
    bots = await repo.list_active_bots()
    for row in bots:
        start_bot_task(row["id"])
    log.info("Started %d child bot(s)", len(bots))


async def stop_all() -> None:
    for bid in list(_tasks.keys()):
        stop_bot_task(bid)


async def notify_user(user_id: int, text: str) -> None:
    """Best-effort DM through the mother bot."""
    from .. import config

    if not config.BOT_TOKEN:
        return
    try:
        bot = Bot(token=config.BOT_TOKEN)
        try:
            await bot.send_message(user_id, text, disable_web_page_preview=True)
        finally:
            await bot.session.close()
    except Exception:
        pass
