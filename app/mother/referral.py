"""Referral panel and reward granting."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from .. import config, keyboards, repo, texts

router = Router(name="mother:referral")


def _referral_link(username: str | None, user_id: int) -> str:
    bot_username = username or "your_bot"
    return f"https://t.me/{bot_username}?start=ref{user_id}"


async def _send_referral_panel(message_or_cb_message, user_id: int, bot_username: str | None) -> None:
    count = await repo.count_referrals(user_id)
    rewards = await repo.rewarded_referrals(user_id)
    need = config.REFERRAL_INVITES
    remaining = (need - (count % need)) % need or need
    link = _referral_link(bot_username, user_id)
    await message_or_cb_message.answer(
        texts.REFERRAL_MENU.format(
            need=need,
            days=config.REFERRAL_REWARD_DAYS,
            count=count,
            rewards=rewards,
            remaining=remaining,
            link=link,
        ),
        reply_markup=keyboards.referral_keyboard(link),
        disable_web_page_preview=True,
    )


async def check_and_reward(user_id: int) -> None:
    """Grant pro days for every complete batch of referrals."""
    count = await repo.count_referrals(user_id)
    rewarded = await repo.rewarded_referrals(user_id)
    need = config.REFERRAL_INVITES
    pending = (count // need) * need - rewarded
    if pending <= 0:
        return
    batches = pending // need
    await repo.mark_referrals_rewarded(user_id, batches * need)
    days = batches * config.REFERRAL_REWARD_DAYS
    await repo.grant_pro(user_id, days)

    from ..child import manager

    await manager.notify_user(
        user_id,
        f"🎁 <b>پاداش دعوت دوستان!</b>\n\n"
        f"به‌خاطر دعوت {batches * need} نفر، <b>{days} روز اشتراک 💎 پرو</b> رایگان گرفتی!\n"
        f"لذت ببر 🚀",
    )


@router.callback_query(F.data == "ref:menu")
async def cb_ref_menu(cb: CallbackQuery) -> None:
    if not cb.message:
        return
    me = await cb.bot.me()
    await _send_referral_panel_via_edit(cb, me.username)


async def _send_referral_panel_via_edit(cb: CallbackQuery, username: str | None) -> None:
    user_id = cb.from_user.id
    count = await repo.count_referrals(user_id)
    rewards = await repo.rewarded_referrals(user_id)
    need = config.REFERRAL_INVITES
    remaining = (need - (count % need)) % need or need
    link = _referral_link(username, user_id)
    await cb.message.edit_text(
        texts.REFERRAL_MENU.format(
            need=need,
            days=config.REFERRAL_REWARD_DAYS,
            count=count,
            rewards=rewards,
            remaining=remaining,
            link=link,
        ),
        reply_markup=keyboards.referral_keyboard(link),
        disable_web_page_preview=True,
    )


@router.message(Command("referral"))
async def cmd_referral(message: Message) -> None:
    me = await message.bot.me()
    await _send_referral_panel(message, message.from_user.id, me.username)
