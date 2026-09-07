"""Middlewares: user registration, ban check, simple anti-spam."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from . import repo, texts


class UserMiddleware(BaseMiddleware):
    """Registers/refreshes the user and blocks banned users."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user = data.get("event_from_user")
        if tg_user is None or tg_user.is_bot:
            return await handler(event, data)

        await repo.upsert_user(tg_user.id, tg_user.first_name, tg_user.username)

        if await repo.is_banned(tg_user.id):
            if isinstance(event, CallbackQuery):
                try:
                    await event.answer(texts.BANNED, show_alert=True)
                except Exception:
                    pass
            elif isinstance(event, Message):
                try:
                    await event.answer(texts.BANNED)
                except Exception:
                    pass
            return None

        return await handler(event, data)


class ThrottleMiddleware(BaseMiddleware):
    """Very light anti-flood: max 8 events per 5 seconds per user.

    (4 was too tight: normal menu navigation — /start + 4 clicks — already
    exceeded it and buttons silently stopped responding.)"""

    RATE_LIMIT = 8
    WINDOW = 5.0

    def __init__(self) -> None:
        self._hits: dict[int, deque[float]] = defaultdict(deque)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user = data.get("event_from_user")
        if tg_user is None or tg_user.is_bot:
            return await handler(event, data)

        now = time.monotonic()
        hits = self._hits[tg_user.id]
        while hits and now - hits[0] > self.WINDOW:
            hits.popleft()

        if len(hits) >= self.RATE_LIMIT:
            if isinstance(event, CallbackQuery):
                try:
                    await event.answer(texts.TOO_SOON, show_alert=False)
                except Exception:
                    pass
            return None  # silently drop

        hits.append(now)
        return await handler(event, data)
