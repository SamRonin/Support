"""Shared handlers for every child bot: support chat in private + business messages."""

from __future__ import annotations

import logging
import time

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.types import Message

from .. import config, repo, texts
from ..ai_client import AIError, build_system_prompt, chat

log = logging.getLogger("child.handlers")

router = Router(name="child")

# conversation memory per (bot_id, chat_id) — pro feature
_history: dict[tuple[int, int], list[dict]] = {}
_HISTORY_MAX = config.CONVERSATION_CONTEXT_MESSAGES * 2

# owner pro cache (2 min TTL) to avoid a DB hit per message
_owner_pro_cache: dict[int, tuple[bool, float]] = {}


def _trim_history(key: tuple[int, int]) -> None:
    h = _history.get(key)
    if h and len(h) > _HISTORY_MAX:
        del h[: len(h) - _HISTORY_MAX]


def _append_history(key: tuple[int, int], role: str, content: str) -> None:
    h = _history.setdefault(key, [])
    h.append({"role": role, "content": content})
    _trim_history(key)


def _build_prompt(bot_row, chat_id: int, user_text: str) -> str:
    """Compose full prompt: system + (pro) conversation memory + user message."""
    system = build_system_prompt(bot_row["title"], bot_row["knowledge"])
    key = (bot_row["id"], chat_id)
    parts = [system]

    history = _history.get(key) or []
    if history:
        convo = "\n".join(
            f"{'مشتری' if m['role'] == 'user' else 'پشتیبانی'}: {m['content']}" for m in history
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


def _append_history_inject(key: tuple[int, int]) -> None:  # pragma: no cover
    raise NotImplementedError


async def _quota_left(bot_row) -> bool:
    """Monthly AI message quota (free vs pro)."""
    is_pro = await _owner_is_pro(bot_row["owner_id"])
    limit = config.PRO_AI_MONTHLY_LIMIT if is_pro else config.FREE_AI_MONTHLY_LIMIT
    used = await repo.month_usage_total(bot_row["id"])
    return used < limit


async def _account_usage(bot_row, chat_id: int) -> None:
    await repo.count_usage(bot_row["id"], chat_id)
    await repo.count_usage(bot_row["id"], 0)  # global counter row for total


# ------------------------------------------------------------------ private
@router.message(F.chat.type == ChatType.PRIVATE, F.text)
async def private_text(message: Message, bot: Bot) -> None:
    bot_row = await repo.get_bot_by_token(bot.token)
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

    if not await _quota_left(bot_row):
        await message.answer(texts.AI_LIMIT_REACHED)
        return

    await bot.send_chat_action(message.chat.id, "typing")
    prompt = _build_prompt(bot_row, message.chat.id, text)
    try:
        reply = await chat(prompt, preferred=bot_row["model"])
    except AIError as e:
        log.error("AI failed for bot #%d: %s", bot_row["id"], e)
        await message.answer("🙏 پیام شما ثبت شد؛ همکاران ما به‌زودی بررسی و پاسخ می‌دهند.")
        return

    _append_history((bot_row["id"], message.chat.id), "user", text)
    _append_history((bot_row["id"], message.chat.id), "assistant", reply)
    await _account_usage(bot_row, message.chat.id)

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

    text = (message.text or "").strip()
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

    try:
        await bot.send_chat_action(
            message.chat.id, "typing", business_connection_id=bc_id
        )
    except Exception:
        pass

    prompt = _build_prompt(bot_row, message.chat.id, text)
    try:
        reply = await chat(prompt, preferred=bot_row["model"])
    except AIError:
        return

    _append_history((bot_row["id"], message.chat.id), "user", text)
    _append_history((bot_row["id"], message.chat.id), "assistant", reply)
    await _account_usage(bot_row, message.chat.id)

    try:
        await bot.send_message(
            message.chat.id, reply[:4000], business_connection_id=bc_id
        )
    except Exception as e:
        log.warning("business reply failed bot#%d: %r", bot_row["id"], e)
