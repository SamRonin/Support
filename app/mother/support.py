"""Support router (Task 4): lets users reach the admin for help.

Adds a «🆘 پشتیبانی» button to the main menu. Tapping it shows a short panel
with a deep-link button that opens the admin's Telegram chat (configured via
SUPPORT_USERNAME, falling back to ADMIN_ID).
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from .. import keyboards, texts

router = Router(name="mother:support")


@router.callback_query(F.data == "support:menu")
async def cb_support(cb: CallbackQuery) -> None:
    if not cb.message:
        await cb.answer()
        return
    await cb.answer()
    await cb.message.edit_text(
        texts.SUPPORT_MENU,
        reply_markup=keyboards.support_keyboard(),
        disable_web_page_preview=True,
    )


@router.message(Command("support"))
async def cmd_support(message: Message) -> None:
    await message.answer(
        texts.SUPPORT_MENU,
        reply_markup=keyboards.support_keyboard(),
        disable_web_page_preview=True,
    )
