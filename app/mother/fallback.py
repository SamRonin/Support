"""Last-resort message handlers — MUST be included as the final router.

Before this fix, a dialog that expired (or got lost across restarts) made the
bot completely silent: the dialog filters stopped matching and nothing
answered. This fallback explains what happened instead of ignoring the user.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import Message

from .. import texts
from ..states import store

router = Router(name="mother:fallback")


@router.message(F.text, ~F.text.startswith("/"))
async def fallback_text(message: Message) -> None:
    expired_action = store.recently_expired_action(message.from_user.id)
    if expired_action:
        await message.answer(texts.DIALOG_EXPIRED)
        return
    # no dialog at all — the user typed something we simply don't understand
    await message.answer(texts.FALLBACK_HINT)
