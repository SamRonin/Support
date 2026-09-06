"""Child bot supervisor: runs a polling task per registered child bot.

Improvements:
- auto-reconnect with exponential backoff (a single network hiccup used to
  kill a child bot until the next full redeploy);
- `get_api_bot()` hands out the LIVE polling Bot instance for one-off API
  calls (settings edits) so they reuse an already-authenticated session
  instead of a fresh TCP+TLS handshake every time;
- stale updates that arrived while the bot was down are dropped by default
  so fresh messages are answered instantly.
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher

from .. import config, repo
from . import handlers

log = logging.getLogger("child.manager")

_tasks: dict[int, asyncio.Task] = {}
_bots: dict[int, Bot] = {}  # bot_id -> Bot instance (owned by the poll loop)
_mother_bot: Bot | None = None

CHILD_ALLOWED_UPDATES = [
    "message",
    "callback_query",
    "business_message",
    "business_connection",
    "channel_post",
]


def _build_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    dp.include_router(handlers.router)
    return dp


def get_api_bot(bot_id: int, token: str) -> Bot:
    """Bot instance for one-off API calls (settings edits, photo uploads...).

    Reuses the live polling bot when available; otherwise caches a dedicated
    instance. Callers must NOT close the session — the manager owns it.
    """
    bot = _bots.get(bot_id)
    if bot is None:
        bot = Bot(token=token)
        _bots[bot_id] = bot
    return bot


async def _poll_loop(bot_id: int, token: str, username: str | None) -> None:
    dp = _build_dispatcher()
    bot = Bot(token=token)
    _bots[bot_id] = bot
    consecutive_failures = 0
    try:
        await bot.delete_webhook(
            drop_pending_updates=config.CHILD_DROP_PENDING_UPDATES
        )
        log.info(
            "Child bot #%d (@%s) polling started", bot_id, username or "?"
        )
        while True:
            started = asyncio.get_running_loop().time()
            try:
                await dp.start_polling(
                    bot,
                    handle_signals=False,
                    allowed_updates=CHILD_ALLOWED_UPDATES,
                )
                return  # polling stopped gracefully
            except asyncio.CancelledError:
                raise
            except Exception as e:
                runtime = asyncio.get_running_loop().time() - started
                if runtime > 300:
                    # ran stably for a while — start counting errors anew
                    consecutive_failures = 0
                    await repo.reset_error_count(bot_id)
                consecutive_failures += 1
                log.error("Child bot #%d crashed: %r", bot_id, e)
                count = await repo.bump_error_count(bot_id)
                if count >= 10:
                    await repo.set_bot_active(bot_id, False)
                    log.error("Child bot #%d disabled after repeated errors", bot_id)
                    return
                delay = min(2 ** consecutive_failures, 60)
                log.warning("Child bot #%d restarting in %ds...", bot_id, delay)
                await asyncio.sleep(delay)
    finally:
        _bots.pop(bot_id, None)
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
        await _poll_loop(bot_id, row["token"], row["username"])

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
    """Best-effort DM through the mother bot (cached instance)."""
    global _mother_bot

    if not config.BOT_TOKEN:
        return
    try:
        if _mother_bot is None:
            _mother_bot = Bot(token=config.BOT_TOKEN)
        await _mother_bot.send_message(user_id, text, disable_web_page_preview=True)
    except Exception:
        pass
