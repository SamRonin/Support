import logging

import asyncpg

from . import config

log = logging.getLogger("db")

_pool: asyncpg.Pool | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id        BIGINT PRIMARY KEY,
    first_name     TEXT,
    username       TEXT,
    is_pro         BOOLEAN NOT NULL DEFAULT FALSE,
    pro_until      TIMESTAMPTZ,
    referrals_count INTEGER NOT NULL DEFAULT 0,
    banned         BOOLEAN NOT NULL DEFAULT FALSE,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS bots (
    id             SERIAL PRIMARY KEY,
    owner_id       BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    token          TEXT NOT NULL UNIQUE,
    username       TEXT,
    title          TEXT,
    active         BOOLEAN NOT NULL DEFAULT TRUE,
    error_count    INTEGER NOT NULL DEFAULT 0,
    knowledge      TEXT NOT NULL DEFAULT '',
    channels       TEXT[] NOT NULL DEFAULT '{}',
    welcome_message TEXT,
    model          TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_bots_owner ON bots(owner_id);

CREATE TABLE IF NOT EXISTS payments (
    id             SERIAL PRIMARY KEY,
    user_id        BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    amount         INTEGER NOT NULL,
    receipt_text   TEXT,
    receipt_file_id TEXT,
    status         TEXT NOT NULL DEFAULT 'pending',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    decided_at     TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS referrals (
    id             SERIAL PRIMARY KEY,
    referrer_id    BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    invited_id     BIGINT NOT NULL UNIQUE REFERENCES users(user_id) ON DELETE CASCADE,
    rewarded       BOOLEAN NOT NULL DEFAULT FALSE,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS usage (
    id             SERIAL PRIMARY KEY,
    bot_id         INTEGER NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    period         TEXT NOT NULL,
    chat_id        BIGINT NOT NULL,
    count          INTEGER NOT NULL DEFAULT 1,
    UNIQUE (bot_id, period, chat_id)
);
CREATE INDEX IF NOT EXISTS idx_usage_bot_period ON usage(bot_id, period);
"""


async def init_pool() -> asyncpg.Pool:
    global _pool
    if _pool is not None:
        return _pool

    url = config.DATABASE_URL
    # asyncpg needs plain postgres:// URLs converted
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)

    _pool = await asyncpg.create_pool(
        url,
        min_size=1,
        max_size=10,          # was 5 — many child bots + mother polling need headroom
        command_timeout=30,
        statement_cache_size=0,  # required for some pooled providers (e.g. PgBouncer)
    )
    async with _pool.acquire() as conn:
        await conn.execute(SCHEMA)
    log.info("Database pool ready")
    return _pool


def pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB pool is not initialised")
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        log.info("Database pool closed")
