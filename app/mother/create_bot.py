"""Create-bot wizard: user sends a child bot token, we validate & launch it."""

from __future__ import annotations

import re

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import CallbackQuery, Message

from .. import config, keyboards, repo, texts
from ..child import manager
from ..states import Dialog, store

router = Router(name="mother:create")

TOKEN_RE = re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{30,}\b")


@router.callback_query(F.data == "bot:create")
async def cb_create(cb: CallbackQuery) -> None:
    if not cb.message:
        return
    user = await repo.get_user(cb.from_user.id)
    bots = await repo.list_user_bots(cb.from_user.id)
    is_pro = repo.is_pro_row(user)
    max_bots = config.PRO_MAX_BOTS if is_pro else config.FREE_MAX_BOTS
    if len(bots) >= max_bots:
        await cb.answer()
        await cb.message.answer(
            texts.BOT_LIMIT_REACHED.format(max=max_bots),
            reply_markup=keyboards.back_to_menu(),
        )
        return

    store.set(cb.from_user.id, Dialog(action="create:token"))
    await cb.message.edit_text(texts.CREATE_BOT_ASK_TOKEN, disable_web_page_preview=True)


@router.message(Dialog.action_filter("create:token"))
async def msg_token(message: Message) -> None:
    user_id = message.from_user.id
    token = (message.text or "").strip()
    m = TOKEN_RE.search(token)
    if not m:
        await message.answer(texts.INVALID_TOKEN)
        return
    token = m.group(0)

    # validate via getMe using a temporary Bot instance
    temp = Bot(token=token)
    try:
        me = await temp.get_me()
    except (TelegramAPIError, TelegramBadRequest):
        await message.answer(texts.INVALID_TOKEN)
        return
    finally:
        await temp.session.close()

    username = me.username or ""
    title = me.first_name or "My Bot"

    existing = await repo.get_bot_by_token(token)
    if existing:
        await message.answer("⚠️ این ربات قبلاً ثبت شده است!")
        store.pop(user_id)
        return

    bot_id = await repo.create_bot(user_id, token, username, title)
    store.pop(user_id)

    await manager.start_bot_task(bot_id)
    await message.answer(
        texts.BOT_CREATED.format(title=title, username=username),
        disable_web_page_preview=True,
    )
