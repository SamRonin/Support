"""Shared dialog-state store for mother-bot conversations (memory based)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from aiogram.filters import BaseFilter
from aiogram.types import Message


@dataclass
class Dialog:
    action: str
    bot_id: int | None = None
    payment_id: int | None = None
    target_user_id: int | None = None  # admin panel: user a dialog is about
    text: str | None = None            # admin panel: staged broadcast text
    created_at: float = field(default_factory=time.monotonic)


class DialogStore:
    TTL = 900  # seconds — generous, so long texts (business knowledge) don't expire mid-typing

    def __init__(self) -> None:
        self._data: dict[int, Dialog] = {}
        self._expired: dict[int, tuple[str, float]] = {}  # user -> (action, when)

    def set(self, user_id: int, dialog: Dialog) -> None:
        self._cleanup()
        self._expired.pop(user_id, None)
        self._data[user_id] = dialog

    def get(self, user_id: int) -> Dialog | None:
        d = self._data.get(user_id)
        if d is None:
            return None
        now = time.monotonic()
        if now - d.created_at > self.TTL:
            self._data.pop(user_id, None)
            # remember it so the fallback handler can explain the silence
            self._expired[user_id] = (d.action, now)
            return None
        # refresh TTL on activity: an actively-used dialog never expires mid-flow
        d.created_at = now
        return d

    def pop(self, user_id: int) -> Dialog | None:
        d = self.get(user_id)
        self._data.pop(user_id, None)
        return d

    def recently_expired_action(self, user_id: int) -> str | None:
        """One-shot: the dialog action that just expired (within 60s), if any."""
        entry = self._expired.get(user_id)
        if entry is None:
            return None
        action, ts = entry
        self._expired.pop(user_id, None)
        if time.monotonic() - ts > 60:
            return None
        return action

    def _cleanup(self) -> None:
        now = time.monotonic()
        expired = [uid for uid, d in self._data.items() if now - d.created_at > self.TTL]
        for uid in expired:
            d = self._data.pop(uid)
            self._expired[uid] = (d.action, now)
        stale = [uid for uid, (_, ts) in self._expired.items() if now - ts > 60]
        for uid in stale:
            self._expired.pop(uid, None)


store = DialogStore()


class DialogFilter(BaseFilter):
    """Match messages from users having a dialog with the given action.

    IMPORTANT: this class MUST subclass ``aiogram`` ``BaseFilter``.
    A plain callable instance with ``async def __call__`` is NOT detected
    as awaitable by aiogram (``inspect.iscoroutinefunction`` returns False
    for instances), so the returned coroutine is never awaited and the
    truthy coroutine object makes the filter match EVERY message.
    That was the root cause of the "invalid token" bug on every settings
    input: the create-token handler swallowed all text messages.
    Subclassing BaseFilter makes aiogram await the filter properly.
    """

    def __init__(self, action: str) -> None:
        self.action = action

    async def __call__(self, message: Message) -> bool:
        d = store.get(message.from_user.id)
        return bool(d and d.action == self.action)


def action_filter(action: str) -> DialogFilter:
    return DialogFilter(action)


# Attach helper so handlers can write Dialog.action_filter("...")
Dialog.action_filter = staticmethod(action_filter)  # type: ignore[attr-defined]
