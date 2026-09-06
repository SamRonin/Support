"""Shared dialog-state store for mother-bot conversations (memory based)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class Dialog:
    action: str
    bot_id: int | None = None
    payment_id: int | None = None
    created_at: float = field(default_factory=time.monotonic)


class DialogStore:
    TTL = 600  # seconds

    def __init__(self) -> None:
        self._data: dict[int, Dialog] = {}

    def set(self, user_id: int, dialog: Dialog) -> None:
        self._cleanup()
        self._data[user_id] = dialog

    def get(self, user_id: int) -> Dialog | None:
        d = self._data.get(user_id)
        if d is None or time.monotonic() - d.created_at > self.TTL:
            self._data.pop(user_id, None)
            return None
        return d

    def pop(self, user_id: int) -> Dialog | None:
        d = self.get(user_id)
        self._data.pop(user_id, None)
        return d

    def _cleanup(self) -> None:
        now = time.monotonic()
        expired = [uid for uid, d in self._data.items() if now - d.created_at > self.TTL]
        for uid in expired:
            self._data.pop(uid, None)


store = DialogStore()


class DialogFilter:
    """Match messages from users having a dialog with the given action."""

    def __init__(self, action: str) -> None:
        self.action = action

    async def __call__(self, message) -> bool:
        d = store.get(message.from_user.id)
        return bool(d and d.action == self.action)


def action_filter(action: str) -> DialogFilter:
    return DialogFilter(action)


# Attach helper so handlers can write Dialog.action_filter("...")
def _action_filter(action: str) -> DialogFilter:
    return DialogFilter(action)


Dialog.action_filter = staticmethod(_action_filter)  # type: ignore[attr-defined]
