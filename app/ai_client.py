"""OmegaTech Aicli client with model fallback + retry.

Endpoint: GET/POST https://omegatech-api.dixonomega.tech/api/ai/Aicli
  action=chat  model=<id>  query=<prompt>  ->  {"success": true, "data": {"reply": "..."}}
"""

from __future__ import annotations

import asyncio
import logging
import random

import httpx

from . import config

log = logging.getLogger("ai")

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=config.AI_TIMEOUT)
    return _client


async def close_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


class AIError(Exception):
    """Raised when every model attempt failed."""


def build_system_prompt(bot_title: str | None, knowledge: str) -> str:
    title = bot_title or "این کسب‌وکار"
    return (
        "تو دستیار پشتیبانی مشتریان هستی و در تلگرام داری به پیام‌های مشتریان "
        f"«{title}» جواب می‌دهی؛ طوری جواب بده که انگار خود ادمینِ این کسب‌وکار داری جواب می‌دهی.\n"
        "قوانین پاسخ‌گویی:\n"
        "1. همیشه به زبان پیام کاربر جواب بده (فارسی، فارسی؛ انگلیسی، انگلیسی).\n"
        "2. فقط بر اساس «اطلاعات کسب‌وکار» جواب بده و چیزی از خودت نساز.\n"
        "3. اگر جواب را نمی‌دانی یا اطلاعات کافی نیست، محترمانه بگو که پیامش برای ادمین ارسال شد و به‌زودی پیگیری می‌شود. قیمت و قول دقیق از خودت درنیاور.\n"
        "4. جواب‌ها کوتاه، دوستانه و حرفه‌ای باشند (معمولاً ۱ تا ۴ جمله) و بدون هدینگ و لیست طولانی.\n"
        "5. هرگز نگو که تو ربات یا هوش مصنوعی هستی؛ تو کارمند پشتیبانی هستی.\n\n"
        f"اطلاعات کسب‌وکار:\n{knowledge if knowledge.strip() else '(اطلاعاتی ثبت نشده؛ محتاط و کلی جواب بده و وعده دقیق نده.)'}"
    )


async def _ask_once(model: str, prompt: str) -> str:
    payload = {"action": "chat", "model": model, "query": prompt}
    r = await _get_client().post(config.AI_API_URL, json=payload)
    if r.status_code != 200:
        raise AIError(f"{model}: HTTP {r.status_code}")
    try:
        body = r.json()
    except ValueError:
        raise AIError(f"{model}: non-json response")
    if not body.get("success"):
        raise AIError(f"{model}: success=false")
    data = body.get("data") or {}
    reply = data.get("reply")
    if not reply or not str(reply).strip():
        raise AIError(f"{model}: empty reply")
    return str(reply).strip()


async def chat(prompt: str, preferred: str | None = None) -> str:
    """Send prompt; try preferred model first, then the fallback chain."""
    chain: list[str] = []
    if preferred and preferred in config.SUPPORTED_MODELS:
        chain.append(preferred)
    for m in config.FALLBACK_MODELS:
        if m not in chain:
            chain.append(m)
    if not chain:
        raise AIError("no models configured")

    errors: list[str] = []
    for attempt, model in enumerate(chain):
        try:
            reply = await _ask_once(model, prompt)
            return reply
        except AIError as e:
            errors.append(str(e))
            log.warning("AI attempt %d/%d failed: %s", attempt + 1, len(chain), e)
        except (httpx.HTTPError, asyncio.TimeoutError) as e:
            errors.append(f"{model}: {e!r}")
            log.warning("AI network error on %s: %r", model, e)
        # brief backoff before next attempt
        await asyncio.sleep(0.8 + random.random() * 0.7)

    raise AIError("all models failed: " + " | ".join(errors[:4]))
