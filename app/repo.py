"""High-level data access helpers (users, bots, payments, referrals, usage).

Adds small in-memory caches (invalidated on every write through this process)
so the hot path of child bots does not hammer Postgres on every message.
Single-process deployment => write-through invalidation keeps caches correct.
"""

from __future__ import annotations

import datetime as dt
import time

from . import config, db

UTC = dt.timezone.utc

# ---------------------------------------------------------------- caches
_BOT_TTL = 120.0          # bot rows (also invalidated on every write)
_USER_UPSERT_TTL = 3600.0  # refresh user profile at most once per hour
_BAN_TTL = 60.0           # ban flag cache
_USAGE_TTL = 15.0         # monthly usage counter (soft quota, short TTL)

_bot_cache: dict[int, dict] = {}        # bot_id -> row
_bot_token_index: dict[str, int] = {}   # token -> bot_id
_user_cache: dict[int, dict] = {}       # user_id -> row
_user_upsert_at: dict[int, tuple[str | None, str | None, float]] = {}
_ban_cache: dict[int, tuple[bool, float]] = {}
_usage_cache: dict[tuple[int, str], tuple[int, float]] = {}


def _cache_bot(row) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    _bot_cache[d["id"]] = d
    if d.get("token"):
        _bot_token_index[d["token"]] = d["id"]
    return d


def _invalidate_bot(bot_id: int | None = None, token: str | None = None) -> None:
    if bot_id is not None:
        row = _bot_cache.pop(bot_id, None)
        if row and row.get("token"):
            _bot_token_index.pop(row["token"], None)
    if token is not None:
        bot_id = _bot_token_index.pop(token, None)
        if bot_id is not None:
            _bot_cache.pop(bot_id, None)


def invalidate_user(user_id: int) -> None:
    _user_cache.pop(user_id, None)
    _ban_cache.pop(user_id, None)
    _user_upsert_at.pop(user_id, None)


# ---------------------------------------------------------------- users
async def upsert_user(user_id: int, first_name: str | None, username: str | None) -> None:
    """Insert/refresh user; throttled — at most one write per hour per user
    unless name/username actually changed (was: a DB write on EVERY event)."""
    now = time.monotonic()
    seen = _user_upsert_at.get(user_id)
    if seen and seen[0] == first_name and seen[1] == username and now - seen[2] < _USER_UPSERT_TTL:
        return
    _user_upsert_at[user_id] = (first_name, username, now)

    await db.pool().execute(
        """
        INSERT INTO users (user_id, first_name, username)
        VALUES ($1, $2, $3)
        ON CONFLICT (user_id) DO UPDATE
        SET first_name = COALESCE(EXCLUDED.first_name, users.first_name),
            username   = COALESCE(EXCLUDED.username, users.username)
        """,
        user_id, first_name, username,
    )
    _user_cache.pop(user_id, None)


async def get_user(user_id: int):
    row = await db.pool().fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
    if row is None:
        return None
    d = dict(row)
    _user_cache[user_id] = d
    return d


async def set_banned(user_id: int, banned: bool) -> None:
    await db.pool().execute("UPDATE users SET banned = $2 WHERE user_id = $1", user_id, banned)
    invalidate_user(user_id)


async def is_banned(user_id: int) -> bool:
    hit = _ban_cache.get(user_id)
    now = time.monotonic()
    if hit and now - hit[1] < _BAN_TTL:
        return hit[0]
    row = await db.pool().fetchval("SELECT banned FROM users WHERE user_id = $1", user_id)
    val = bool(row)
    _ban_cache[user_id] = (val, now)
    return val


async def grant_pro(user_id: int, days: int) -> None:
    """Extend pro membership (from now, or from current expiry if still active)."""
    row = await get_user(user_id)
    if row and row["pro_until"] and row["pro_until"] > dt.datetime.now(UTC):
        base = row["pro_until"]
    else:
        base = dt.datetime.now(UTC)
    until = base + dt.timedelta(days=days)
    await db.pool().execute(
        "UPDATE users SET is_pro = TRUE, pro_until = $2 WHERE user_id = $1",
        user_id, until,
    )
    invalidate_user(user_id)


async def revoke_pro(user_id: int) -> None:
    await db.pool().execute(
        "UPDATE users SET is_pro = FALSE, pro_until = NULL WHERE user_id = $1", user_id
    )
    invalidate_user(user_id)


async def refresh_pro_flags() -> None:
    """Downgrade users whose subscription ended."""
    await db.pool().execute(
        "UPDATE users SET is_pro = FALSE WHERE is_pro = TRUE AND pro_until IS NOT NULL AND pro_until < now()"
    )
    _user_cache.clear()


def is_pro_row(user_row) -> bool:
    if not user_row or not user_row["is_pro"]:
        return False
    until = user_row["pro_until"]
    return until is None or until > dt.datetime.now(UTC)


# ---------------------------------------------------------------- bots
async def create_bot(owner_id: int, token: str, username: str | None, title: str | None) -> int:
    bot_id = await db.pool().fetchval(
        """
        INSERT INTO bots (owner_id, token, username, title)
        VALUES ($1, $2, $3, $4)
        RETURNING id
        """,
        owner_id, token, username, title,
    )
    _invalidate_bot(bot_id=bot_id, token=token)
    return bot_id


async def get_bot(bot_id: int):
    hit = _bot_cache.get(bot_id)
    if hit is not None:
        return hit
    row = await db.pool().fetchrow("SELECT * FROM bots WHERE id = $1", bot_id)
    return _cache_bot(row)


async def get_bot_by_token(token: str):
    bot_id = _bot_token_index.get(token)
    if bot_id is not None:
        hit = _bot_cache.get(bot_id)
        if hit is not None:
            return hit
    row = await db.pool().fetchrow("SELECT * FROM bots WHERE token = $1", token)
    return _cache_bot(row)


async def get_bot_by_username(username: str):
    uname = username.lstrip("@").lower()
    return await db.pool().fetchrow(
        "SELECT * FROM bots WHERE lower(username) = $1", uname
    )


async def list_user_bots(owner_id: int):
    return await db.pool().fetch(
        "SELECT * FROM bots WHERE owner_id = $1 ORDER BY id", owner_id
    )


async def list_active_bots():
    return await db.pool().fetch("SELECT * FROM bots WHERE active = TRUE")


async def set_bot_active(bot_id: int, active: bool) -> None:
    await db.pool().execute("UPDATE bots SET active = $2 WHERE id = $1", bot_id, active)
    _invalidate_bot(bot_id=bot_id)


async def bump_error_count(bot_id: int) -> int:
    count = await db.pool().fetchval(
        "UPDATE bots SET error_count = error_count + 1 WHERE id = $1 RETURNING error_count",
        bot_id,
    )
    _invalidate_bot(bot_id=bot_id)
    return count or 0


async def reset_error_count(bot_id: int) -> None:
    await db.pool().execute("UPDATE bots SET error_count = 0 WHERE id = $1", bot_id)
    _invalidate_bot(bot_id=bot_id)


async def delete_bot(bot_id: int) -> None:
    row = _bot_cache.get(bot_id)
    await db.pool().execute("DELETE FROM bots WHERE id = $1", bot_id)
    _invalidate_bot(bot_id=bot_id)
    if row:
        _bot_token_index.pop(row.get("token"), None)


async def set_bot_title(bot_id: int, title: str) -> None:
    await db.pool().execute("UPDATE bots SET title = $2 WHERE id = $1", bot_id, title)
    _invalidate_bot(bot_id=bot_id)


async def set_bot_knowledge(bot_id: int, knowledge: str) -> None:
    await db.pool().execute("UPDATE bots SET knowledge = $2 WHERE id = $1", bot_id, knowledge)
    _invalidate_bot(bot_id=bot_id)


async def set_bot_welcome(bot_id: int, welcome: str | None) -> None:
    await db.pool().execute("UPDATE bots SET welcome_message = $2 WHERE id = $1", bot_id, welcome)
    _invalidate_bot(bot_id=bot_id)


async def set_bot_model(bot_id: int, model: str | None) -> None:
    await db.pool().execute("UPDATE bots SET model = $2 WHERE id = $1", bot_id, model)
    _invalidate_bot(bot_id=bot_id)


def _normalize_channel(channel: str) -> str:
    """Public usernames are case-insensitive; private invite codes are NOT —
    lowercasing an invite code used to break it (old bug)."""
    channel = (channel or "").strip().lstrip("@")
    if channel.startswith("+"):
        return channel  # case-sensitive invite code
    return channel.lower()


async def add_bot_channel(bot_id: int, channel: str) -> None:
    ch = _normalize_channel(channel)
    await db.pool().execute(
        "UPDATE bots SET channels = array_append(channels, $2) "
        "WHERE id = $1 AND NOT ($2 = ANY(channels))",
        bot_id, ch,
    )
    _invalidate_bot(bot_id=bot_id)


async def remove_bot_channel(bot_id: int, channel: str) -> None:
    ch = _normalize_channel(channel)
    await db.pool().execute(
        "UPDATE bots SET channels = array_remove(channels, $2) WHERE id = $1",
        bot_id, ch,
    )
    _invalidate_bot(bot_id=bot_id)


# ---------------------------------------------------------------- payments
async def create_payment(user_id: int, amount: int) -> int:
    return await db.pool().fetchval(
        "INSERT INTO payments (user_id, amount) VALUES ($1, $2) RETURNING id",
        user_id, amount,
    )


async def set_payment_receipt(payment_id: int, text: str | None, file_id: str | None) -> None:
    await db.pool().execute(
        "UPDATE payments SET receipt_text = $2, receipt_file_id = $3 WHERE id = $1",
        payment_id, text, file_id,
    )


async def decide_payment(payment_id: int, status: str) -> None:
    await db.pool().execute(
        "UPDATE payments SET status = $2, decided_at = now() WHERE id = $1 AND status = 'pending'",
        payment_id, status,
    )


async def get_payment(payment_id: int):
    return await db.pool().fetchrow("SELECT * FROM payments WHERE id = $1", payment_id)


# ---------------------------------------------------------------- referrals
async def register_referral(referrer_id: int, invited_id: int) -> bool:
    """Insert referral; returns True if it is new (first time this invitee)."""
    status = await db.pool().fetchval(
        """
        INSERT INTO referrals (referrer_id, invited_id)
        VALUES ($1, $2)
        ON CONFLICT (invited_id) DO NOTHING
        RETURNING TRUE
        """,
        referrer_id, invited_id,
    )
    return bool(status)


async def count_referrals(referrer_id: int) -> int:
    return await db.pool().fetchval(
        "SELECT count(*) FROM referrals WHERE referrer_id = $1", referrer_id
    )


async def rewarded_referrals(referrer_id: int) -> int:
    return await db.pool().fetchval(
        "SELECT count(*) FROM referrals WHERE referrer_id = $1 AND rewarded = TRUE", referrer_id
    )


async def mark_referrals_rewarded(referrer_id: int, limit_count: int) -> None:
    await db.pool().execute(
        """
        UPDATE referrals SET rewarded = TRUE
        WHERE id IN (
            SELECT id FROM referrals
            WHERE referrer_id = $1 AND rewarded = FALSE
            ORDER BY id
            LIMIT $2
        )
        """,
        referrer_id, limit_count,
    )


# ---------------------------------------------------------------- usage
def _period(now: dt.datetime | None = None) -> str:
    now = now or dt.datetime.now(UTC)
    return f"{now.year:04d}-{now.month:02d}"


async def count_usage(bot_id: int, chat_id: int) -> None:
    """Count chat + global usage rows in ONE round trip (was: two queries)."""
    period = _period()
    await db.pool().execute(
        """
        INSERT INTO usage (bot_id, period, chat_id, count)
        VALUES ($1, $2, $3, 1), ($1, $2, 0, 1)
        ON CONFLICT (bot_id, period, chat_id)
        DO UPDATE SET count = usage.count + 1
        """,
        bot_id, period, chat_id,
    )
    _usage_cache.pop((bot_id, period), None)


async def month_usage_total(bot_id: int) -> int:
    key = (bot_id, _period())
    hit = _usage_cache.get(key)
    if hit and time.monotonic() - hit[1] < _USAGE_TTL:
        return hit[0]
    val = await db.pool().fetchval(
        "SELECT COALESCE(sum(count), 0) FROM usage WHERE bot_id = $1 AND period = $2",
        key[0], key[1],
    )
    _usage_cache[key] = (val or 0, time.monotonic())
    return val or 0


async def month_unique_chats(bot_id: int) -> int:
    return await db.pool().fetchval(
        "SELECT count(*) FROM usage WHERE bot_id = $1 AND period = $2",
        bot_id, _period(),
    )
