import os


def _int_env(key: str, default: int) -> int:
    raw = os.getenv(key, "").strip()
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _bool_env(key: str, default: bool) -> bool:
    raw = os.getenv(key, "").strip().lower()
    if not raw:
        return default
    return raw not in ("0", "false", "no", "off")


BOT_TOKEN = os.getenv("MOTHER_BOT_TOKEN", "").strip()
ADMIN_ID = _int_env("ADMIN_ID", 0)
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

PRIVATE_CHANNEL_ID = _int_env("PRIVATE_CHANNEL_ID", 0)

CARD_NUMBER = os.getenv("CARD_NUMBER", "0000-0000-0000-0000").strip()
CARD_HOLDER = os.getenv("CARD_HOLDER", "نام صاحب کارت").strip()
PRO_PRICE_TOMAN = _int_env("PRO_PRICE_TOMAN", 99000)
PRO_DURATION_DAYS = _int_env("PRO_DURATION_DAYS", 30)

REFERRAL_INVITES = _int_env("REFERRAL_INVITES", 3)
REFERRAL_REWARD_DAYS = _int_env("REFERRAL_REWARD_DAYS", 10)

# --- Support contact (Task 4) ---------------------------------------------
# Telegram username (without @) that users reach from the "🆘 پشتیبانی" button.
# When empty, the button falls back to a deep link with the numeric ADMIN_ID.
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "").strip().lstrip("@")

# --- Modern bot-creation: Managed Bots (Task 3) ---------------------------
# Telegram's native "Create Bot" modal (the screenshot you sent) is triggered
# by opening a link of the form:
#     https://t.me/newbot/{mother_bot_username}/{suggested_username}?name={name}
# This requires the mother bot to have "Bot Management Mode" enabled in
# @BotFather (one-time setup). When the user confirms the modal, Telegram
# sends a `managed_bot` update to the mother bot, which then calls
# getManagedBotToken() to fetch the new bot's token and starts polling it.
#
# The mother bot's own @username is fetched automatically at startup
# (see app/child/manager.py) and cached here; no env var needed.
MOTHER_BOT_USERNAME: str = ""  # set at startup by manager.bootstrap_mother()

# When True, the "manual token" fallback button is also offered alongside the
# native Create-Bot button. Useful while Bot Management Mode isn't enabled yet.
CREATE_BOT_SHOW_TOKEN_FALLBACK = _bool_env("CREATE_BOT_SHOW_TOKEN_FALLBACK", True)

# Plans -------------------------------------------------------------------
FREE_MAX_BOTS = 1
PRO_MAX_BOTS = 3
FREE_KNOWLEDGE_CHARS = 1500
PRO_KNOWLEDGE_CHARS = 6000
FREE_CHANNEL_LIMIT = 1
PRO_CHANNEL_LIMIT = 3
FREE_AI_MONTHLY_LIMIT = 300
PRO_AI_MONTHLY_LIMIT = 3000
CONVERSATION_CONTEXT_MESSAGES = 10  # Pro: last N messages as context

FREE_MODELS = ["gpt", "claude", "gemini"]
PRO_MODELS = ["chatgpt_5_5", "claudesonnet", "geminipro"]
FALLBACK_MODELS = [
    "chatgpt_5_5", "claudesonnet", "geminipro",
    "gpt", "claude", "gemini", "chatgpt_auto",
]

AI_API_URL = "https://omegatech-api.dixonomega.tech/api/ai/Aicli"

# --- speed tuning (was: 90s timeout + sequential fallback with sleeps) ---
AI_TIMEOUT = _int_env("AI_TIMEOUT", 30)            # per-request timeout (seconds)
AI_HEDGE_DELAY = float(os.getenv("AI_HEDGE_DELAY", "2.5"))  # start a parallel model after N seconds
AI_MAX_PARALLEL = _int_env("AI_MAX_PARALLEL", 3)   # max simultaneous model attempts

# Drop updates that arrived while a child bot was down (redeploys etc.) so
# fresh messages are answered instantly instead of first grinding a stale backlog.
CHILD_DROP_PENDING_UPDATES = _bool_env("CHILD_DROP_PENDING_UPDATES", True)

SUPPORTED_MODELS = {
    "chatgpt_5_5": "ChatGPT 5.5",
    "claudesonnet": "Claude Sonnet",
    "geminipro": "Gemini Pro",
    "gpt": "GPT",
    "claude": "Claude",
    "gemini": "Gemini",
    "chatgpt_auto": "ChatGPT Auto",
}


def is_admin(user_id: int) -> bool:
    return ADMIN_ID and user_id == ADMIN_ID
