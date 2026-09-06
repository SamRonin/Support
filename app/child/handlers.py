"""Shared handlers for every child bot: support chat in private + business messages.

Speed:
- typing indicator repeats while the AI is thinking (a single chat action
  expires after ~5s and made the bot look stuck);
- bot row / pro status / quota are cached so the hot path adds no DB chatter;
- conversation memory is a Pro feature (as documented) and is bounded.
"""

from __future__ import annotations

import asyncio
import logging
import time

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.types import Message

from .. import config, repo, texts
from ..ai_client import AIError, build_system_prompt, chat

log = logging.getLogger("child.handlers")

router = Router(name="child")

# conversation memory per (bot_id, chat_id) — PRO feature, bounded
_history: dict[tuple[int, int], dict] = {}  # key -> {"msgs": [...], "ts": last_used}
_HISTORY_MAX = config.CONVERSATION_CONTEXT_MESSAGES * 2
_HISTORY_MAX_KEYS = 5000

# owner pro cache (2 min TTL) to avoid a DB hit per message
_owner_pro_cache: dict[int, tuple[bool, float]] = {}

TYPING_INTERVAL = 4.5  # seconds; Telegram "typing…" indicator lasts ~5s


def _evict_history() -> None:
    if len(_history) <= _HISTORY_MAX_KEYS:
        return
    items = sorted(_history.items(), key=lambda kv: kv[1]["ts"])
    for k, _ in items[: len(items) // 5 + 1]:
        _history.pop(k, None)


def _append_history(key: tuple[int, int], role: str, content: str) -> None:
    entry = _history.setdefault(key, {"msgs": [], "ts": 0.0})
    entry["ts"] = time.monotonic()
    msgs = entry["msgs"]
    msgs.append({"role": role, "content": content})
    if len(msgs) > _HISTORY_MAX:
        del msgs[: len(msgs) - _HISTORY_MAX]
    _evict_history()


def _build_prompt(bot_row, chat_id: int, user_text: str, is_pro: bool) -> str:
    """Compose full prompt: system + (pro) conversation memory + user message."""
    system = build_system_prompt(bot_row["title"], bot_row["knowledge"])
    parts = [system]

    if is_pro:  # memory is a Pro-only feature
        key = (bot_row["id"], chat_id)
        entry = _history.get(key)
        if entry and entry["msgs"]:
            convo = "\n".join(
                f"{'مشتری' if m['role'] == 'user' else 'پشتیبانی'}: {m['content']}"
                for m in entry["msgs"]
            )
            parts.append("گفتگوی قبلی با همین مشتری:\n" + convo)

    parts.append("پیام جدید مشتری: " + user_text)
    return "\n\n".join(parts)


async def _owner_is_pro(owner_id: int) -> bool:
    cached = _owner_pro_cache.get(owner_id)
    if cached and time.monotonic() - cached[1] < 120:
        return cached[0]
    owner = await repo.get_user(owner_id)
    is_pro = repo.is_pro_row(owner)
    _owner_pro_cache[owner_id] = (is_pro, time.monotonic())
    return is_pro


def invalidate_owner_cache(owner_id: int) -> None:
    _owner_pro_cache.pop(owner_id, None)


async def _quota_left(bot_row, is_pro: bool | None = None) -> bool:
    """Monthly AI message quota (free vs pro)."""
    if is_pro is None:
        is_pro = await _owner_is_pro(bot_row["owner_id"])
    limit = config.PRO_AI_MONTHLY_LIMIT if is_pro else config.FREE_AI_MONTHLY_LIMIT
    used = await repo.month_usage_total(bot_row["id"])  # 15s cache in repo
    return used < limit


async def _account_usage(bot_row, chat_id: int) -> None:
    await repo.count_usage(bot_row["id"], chat_id)  # single round trip


async def _typing_loop(bot: Bot, chat_id: int, business_connection_id: str | None = None) -> None:
    """Keep the "typing…" indicator alive while the AI is thinking."""
    try:
        while True:
            try:
                await bot.send_chat_action(
                    chat_id, "typing", business_connection_id=business_connection_id
                )
            except Exception:
                pass
            await asyncio.sleep(TYPING_INTERVAL)
    except asyncio.CancelledError:
        raise


async def _reply_with_ai(message: Message, bot: Bot, bot_row, text: str) -> None:
    """Shared AI reply pipeline (typing + hedged AI call + history + quota)."""
    is_pro = await _owner_is_pro(bot_row["owner_id"])
    bc_id = getattr(message, "business_connection_id", None)

    typing_task = asyncio.create_task(_typing_loop(bot, message.chat.id, bc_id))
    try:
        prompt = _build_prompt(bot_row, message.chat.id, text, is_pro)
        reply = await chat(prompt, preferred=bot_row["model"])
    except AIError as e:
        log.error("AI failed for bot #%d: %s", bot_row["id"], e)
        return None  # caller decides how to apologise
    finally:
        typing_task.cancel()
        try:
            await typing_task
        except (asyncio.CancelledError, Exception):
            pass

    if is_pro:
        key = (bot_row["id"], message.chat.id)
        _append_history(key, "user", text)
        _append_history(key, "assistant", reply)
    await _account_usage(bot_row, message.chat.id)
    return reply


# ------------------------------------------------------------------ private
@router.message(F.chat.type == ChatType.PRIVATE, F.text)
async def private_text(message: Message, bot: Bot) -> None:
    bot_row = await repo.get_bot_by_token(bot.token)  # cached
    if not bot_row or not bot_row["active"]:
        return

    text = (message.text or "").strip()
    if text.startswith("/"):
        if text.startswith("/start") and bot_row["welcome_message"]:
            try:
                await message.answer(bot_row["welcome_message"][:4000])
            except Exception:
                pass
        return

    is_pro = await _owner_is_pro(bot_row["owner_id"])
    if not await _quota_left(bot_row, is_pro):
        await message.answer(texts.AI_LIMIT_REACHED)
        return

    reply = await _reply_with_ai(message, bot, bot_row, text)
    if reply is None:
        await message.answer("🙏 پیام شما ثبت شد؛ همکاران ما به‌زودی بررسی و پاسخ می‌دهند.")
        return
    await message.answer(reply[:4000])


@router.message(F.chat.type == ChatType.PRIVATE)
async def private_non_text(message: Message) -> None:
    bot_row = await repo.get_bot_by_token(message.bot.token)
    if not bot_row or not bot_row["active"]:
        return
    await message.answer(
        "🙏 پیام شما دریافت شد! برای پاسخ دقیق‌تر، لطفاً سوالت رو به‌صورت متن بفرست."
    )


# ------------------------------------------------------------------ business
@router.business_message(F.chat.type == ChatType.PRIVATE)
async def business_message(message: Message, bot: Bot) -> None:
    bot_row = await repo.get_bot_by_token(bot.token)
    if not bot_row or not bot_row["active"]:
        return

    text = (message.text or message.caption or "").strip()
    bc_id = message.business_connection_id

    if not text:
        try:
            await bot.send_message(
                message.chat.id,
                "🙏 پیام شما دریافت شد! لطفاً سوالت رو به‌صورت متن بفرست.",
                business_connection_id=bc_id,
            )
        except Exception:
            pass
        return

    if not await _quota_left(bot_row):
        return  # stay silent on business chats when quota exhausted

    reply = await _reply_with_ai(message, bot, bot_row, text)
    if reply is None:
        return

    try:
        await bot.send_message(
            message.chat.id, reply[:4000], business_connection_id=bc_id
        )
    except Exception as e:
        log.warning("business reply failed bot#%d: %r", bot_row["id"], e)


# ------------------------------------------------------------------ channels
@router.channel_post()
async def channel_posts(message: Message, bot: Bot) -> None:
    """Learn from new posts of connected channels (makes the documented
    «اتصال چنل» feature actually feed the bot's knowledge)."""
    bot_row = await repo.get_bot_by_token(bot.token)
    if not bot_row or not bot_row["active"]:
        return

    uname = (message.chat.username or "").lower().lstrip("@")
    if not uname:
        return
    connected = [c.lower().lstrip("@") for c in (bot_row["channels"] or [])]
    if uname not in connected:
        return

    text = (message.text or message.caption or "").strip()
    if not text:
        return

    owner = await repo.get_user(bot_row["owner_id"])
    is_pro = repo.is_pro_row(owner)
    limit = config.PRO_KNOWLEDGE_CHARS if is_pro else config.FREE_KNOWLEDGE_CHARS
    current = (bot_row["knowledge"] or "").strip()
    room = limit - len(current)
    if room <= 0:
        return
    chunk = text[:room].strip()
    new_knowledge = (current + "\n\n" + chunk) if current else chunk
    try:
        await repo.set_bot_knowledge(bot_row["id"], new_knowledge)
        log.info("Bot #%d learned %d chars from @%s", bot_row["id"], len(chunk), uname)
    except Exception as e:
        log.warning("failed to store channel post for bot #%d: %r", bot_row["id"], e)
