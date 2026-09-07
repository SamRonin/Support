"""OmegaTech Aicli client with parallel (hedged) model fallback.

Endpoint: POST https://omegatech-api.dixonomega.tech/api/ai/Aicli
  action=chat  model=<id>  query=<prompt>  ->  {"success": true, "data": {"reply": "..."}}

Speed strategy ("hedged requests"):
- The preferred model is requested immediately.
- If no answer arrives within AI_HEDGE_DELAY seconds, further models from the
  fallback chain are started *in parallel* (up to AI_MAX_PARALLEL at once).
- The first successful reply wins; all remaining attempts are cancelled.
- No artificial sleeps between attempts (previously up to ~1.5s each).
"""

from __future__ import annotations

import asyncio
import logging
import time

import httpx

from . import config
from .lang import lang_fa

log = logging.getLogger("ai")

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(config.AI_TIMEOUT, connect=10.0, pool=10.0),
            limits=httpx.Limits(
                max_connections=30, max_keepalive_connections=15
            ),
            follow_redirects=True,
        )
    return _client


async def close_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


class AIError(Exception):
    """Raised when every model attempt failed."""


def build_system_prompt(
    bot_title: str | None, knowledge: str, user_language: str | None = None
) -> str:
    """System prompt for the support assistant.

    ``user_language``: detected language NAME of the customer's message.
    When known, the prompt hard-pins the reply language in BOTH English and
    Persian (models comply far more reliably when the language is named
    explicitly than with a generic "match the user's language" rule).
    """
    title = bot_title or "این کسب‌وکار"
    if user_language:
        fa = lang_fa(user_language)
        lang_rule = (
            "0. (قانون طلایی) زبان پیام این مشتری: "
            f"«{user_language}» ({fa}). "
            f"LANGUAGE RULE (CRITICAL): Reply ONLY in {user_language} — 100% of the answer "
            f"must be written in {user_language}. Even if the business info or the previous "
            f"conversation is in another language, your answer MUST still be in {user_language} "
            f"({fa}). If the customer switches language, you switch immediately too. "
            "هرگز به زبان دیگری جواب نده؛ حتی یک جمله هم به زبان دیگر اضافه نکن."
        )
    else:
        lang_rule = (
            "0. (قانون طلایی) همیشه دقیقاً به همان زبانی جواب بده که مشتری با آن نوشته "
            "(RESPOND IN THE EXACT LANGUAGE OF THE CUSTOMER'S LAST MESSAGE). "
            "اگر مشتری زبانش را عوض کند، تو هم همان لحظه زبانت را عوض کن."
        )
    return (
        "تو دستیار پشتیبانی مشتریان هستی و در تلگرام داری به پیام‌های مشتریان "
        f"«{title}» جواب می‌دهی؛ طوری جواب بده که انگار خود ادمینِ این کسب‌وکار داری جواب می‌دهی.\n"
        "قوانین پاسخ‌گویی:\n"
        f"{lang_rule}\n"
        "1. فقط بر اساس «اطلاعات کسب‌وکار» جواب بده و چیزی از خودت نساز.\n"
        "2. اگر جواب را نمی‌دانی یا اطلاعات کافی نیست، محترمانه بگو که پیامش برای ادمین ارسال شد و به‌زودی پیگیری می‌شود. قیمت و قول دقیق از خودت درنیاور.\n"
        "3. جواب‌ها کوتاه، دوستانه و حرفه‌ای باشند (معمولاً ۱ تا ۴ جمله) و بدون هدینگ و لیست طولانی.\n"
        "4. هرگز نگو که تو ربات یا هوش مصنوعی هستی؛ تو کارمند پشتیبانی هستی.\n\n"
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


def _build_chain(preferred: str | None) -> list[str]:
    chain: list[str] = []
    if preferred and preferred in config.SUPPORTED_MODELS:
        chain.append(preferred)
    for m in config.FALLBACK_MODELS:
        if m not in chain:
            chain.append(m)
    return chain


async def chat(prompt: str, preferred: str | None = None) -> str:
    """Send the prompt; the first successful model wins (parallel hedging).

    Staggering rules (keeps request load low while cutting wait time):
    - model #0 (preferred) starts immediately;
    - a further model joins only after AI_HEDGE_DELAY without an answer
      OR right away when an in-flight attempt already failed;
    - at most AI_MAX_PARALLEL requests run concurrently.
    """
    chain = _build_chain(preferred)
    if not chain:
        raise AIError("no models configured")

    errors: list[str] = []
    running: dict[asyncio.Task[str], float] = {}  # task -> started_at
    next_idx = 0
    next_allowed = 0.0  # monotonic time when another attempt may be launched

    try:
        while True:
            now = time.monotonic()
            while (
                next_idx < len(chain)
                and len(running) < config.AI_MAX_PARALLEL
                and now >= next_allowed
            ):
                task = asyncio.create_task(_ask_once(chain[next_idx], prompt))
                running[task] = time.monotonic()
                next_idx += 1
                # stagger: the next model joins only if this one is still pending
                next_allowed = running[task] + config.AI_HEDGE_DELAY

            if not running:
                if next_idx >= len(chain):
                    break  # every model tried, nothing in flight
                await asyncio.sleep(max(0.0, next_allowed - time.monotonic()))
                continue

            if next_idx < len(chain):
                wait_timeout = max(0.0, next_allowed - time.monotonic())
            else:
                wait_timeout = None  # chain exhausted: wait for what's in flight
            done, _ = await asyncio.wait(
                set(running), timeout=wait_timeout, return_when=asyncio.FIRST_COMPLETED
            )
            for task in done:
                running.pop(task, None)
                if task.cancelled():
                    continue
                exc = task.exception()
                if exc is None:
                    return task.result()  # first success wins
                errors.append(repr(exc))
                log.warning("AI attempt failed: %r", exc)
                # a failed attempt frees its slot -> allow an immediate replacement
                next_allowed = min(next_allowed, time.monotonic())
    finally:
        # cancel losing attempts and swallow their cancellation
        for task in running:
            task.cancel()
        if running:
            await asyncio.gather(*running, return_exceptions=True)

    raise AIError("all models failed: " + " | ".join(errors[:4]))


# ------------------------------------------------------------------ translation
async def translate_text(text: str, target_language: str) -> str:
    """Translate ``text`` into ``target_language`` (a language NAME like "Persian").

    Used by the child-bot reply pipeline as a safety net: even with the strongest
    possible language-locking prompt, models occasionally answer in the wrong
    language (e.g. they keep answering in Persian when the customer wrote in
    English). When the detected language of the reply does not match the
    detected language of the customer's message, we translate the reply
    ourselves so the user always receives an answer in their own language.

    The same hedged ``chat()`` is reused, so translation inherits the parallel
    fallback, timeouts and error handling for free.
    """
    if not text or not text.strip() or not target_language:
        return text
    fa = lang_fa(target_language) or target_language
    prompt = (
        f"You are a professional translator. Translate the following message into "
        f"{target_language} ({fa}).\n\n"
        f"STRICT RULES:\n"
        f"1. Output ONLY the translated text — no notes, no quotes, no preamble.\n"
        f"2. Preserve the tone, emojis, formatting and line breaks of the original.\n"
        f"3. Do not add or remove information.\n"
        f"4. If the text is already in {target_language}, return it unchanged.\n\n"
        f"Text to translate:\n{text}"
    )
    try:
        translated = await chat(prompt, preferred=None)
    except AIError as e:
        log.warning("translation to %s failed: %r", target_language, e)
        return text  # fall back to the original (possibly wrong-language) reply
    # strip surrounding quotes that models sometimes add
    translated = translated.strip()
    if len(translated) >= 2 and translated[0] in "\"'“”«»" and translated[-1] in "\"'”»«»":
        translated = translated[1:-1].strip()
    return translated or text
