"""Modern create-bot wizard.

New flow (mirrors the native-looking Telegram modal from the screenshot):
1. user taps «🛠 ساخت ربات جدید» -> intro screen with a Web App button
2. the Mini App (webapp/create_bot.html) collects bot NAME + bot USERNAME
   and sends them back to the bot via ``tg.sendData(...)``
3. we receive ``web_app_data``, validate name/username, store them in the
   dialog and show step-by-step BotFather instructions asking for the TOKEN
   (Telegram still requires BotFather to actually mint a bot — there is no
   public API for a bot to create another bot on the user's behalf)
4. user sends the token -> we validate it via ``getMe``, persist + launch

A graceful in-chat fallback (name -> username -> token) is kept so the bot
keeps working even when ``CREATE_BOT_WEBAPP_URL`` is not configured.
"""

from __future__ import annotations

import json
import logging
import re

from aiogram import F, Router
from aiogram.exceptions import TelegramUnauthorizedError, TelegramNetworkError
from aiogram.types import CallbackQuery, Message

from .. import config, keyboards, repo, texts
from ..child import manager
from ..states import Dialog, store

log = logging.getLogger("mother:create")
router = Router(name="mother:create")

# Telegram tokens: <bot_id>:<secret>. No trailing \b — a token may legitimately
# end with "-" or "_" which \b would reject.
TOKEN_RE = re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{30,}")

# Bot username rules: 5-32 chars, [A-Za-z0-9_], must end with "bot" (case-insensitive)
def _normalize_username(raw: str) -> str | None:
    """Return the lowercase username without @, or None when invalid."""
    raw = (raw or "").strip().lstrip("@")
    if not raw:
        return None
    if not raw.endswith("bot"):
        return None
    if not re.fullmatch(r"[A-Za-z0-9_]{5,32}", raw):
        return None
    return raw.lower()


@router.callback_query(F.data == "bot:create")
async def cb_create(cb: CallbackQuery) -> None:
    if not cb.message:
        await cb.answer()
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

    await cb.answer()
    await cb.message.edit_text(
        texts.CREATE_BOT_INTRO,
        reply_markup=keyboards.create_bot_intro_keyboard(),
        disable_web_page_preview=True,
    )


# ------------------------------------------------------------------ in-chat fallback
@router.callback_query(F.data == "bot:create:form")
async def cb_create_form(cb: CallbackQuery) -> None:
    """In-chat fallback when no Mini App URL is configured."""
    if not cb.message:
        await cb.answer()
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

    store.set(cb.from_user.id, Dialog(action="create:name"))
    await cb.answer()
    await cb.message.edit_text(texts.CREATE_BOT_ASK_NAME)


@router.message(Dialog.action_filter("create:name"))
async def msg_create_name(message: Message) -> None:
    name = (message.text or "").strip()
    if not (1 <= len(name) <= 64):
        await message.answer(texts.CREATE_BOT_FORM_INVALID_NAME)
        return
    store.set(message.from_user.id, Dialog(action="create:username", text=name))
    await message.answer(texts.CREATE_BOT_ASK_USERNAME.format(name=name))


@router.message(Dialog.action_filter("create:username"))
async def msg_create_username(message: Message) -> None:
    d = store.get(message.from_user.id)
    if not d or not d.text:
        await message.answer(texts.DIALOG_EXPIRED)
        return
    name = d.text
    username = _normalize_username(message.text or "")
    if not username:
        await message.answer(texts.CREATE_BOT_FORM_INVALID_USERNAME)
        return
    # pack "name\nusername" into dialog.text so the token handler can read both
    store.set(
        message.from_user.id,
        Dialog(action="create:token", text=f"{name}\n{username}"),
    )
    await message.answer(
        texts.CREATE_BOT_ASK_TOKEN_AFTER_FORM.format(name=name, username=username),
        disable_web_page_preview=True,
    )


# ------------------------------------------------------------------ Mini App data
@router.message(F.web_app_data)
async def msg_web_app_data(message: Message) -> None:
    """Receive name + username from the create-bot Mini App."""
    user_id = message.from_user.id
    raw = message.web_app_data.data or ""
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        log.warning("bad web_app_data from %d: %r", user_id, raw)
        await message.answer(texts.GENERIC_ERROR)
        return

    name = (payload.get("name") or "").strip()
    username = _normalize_username(payload.get("username") or "")

    if not (1 <= len(name) <= 64):
        await message.answer(texts.CREATE_BOT_FORM_INVALID_NAME)
        # restart the in-chat fallback so the user is not stuck
        store.set(user_id, Dialog(action="create:name"))
        await message.answer(texts.CREATE_BOT_ASK_NAME)
        return
    if not username:
        await message.answer(texts.CREATE_BOT_FORM_INVALID_USERNAME)
        store.set(user_id, Dialog(action="create:username", text=name))
        await message.answer(texts.CREATE_BOT_ASK_USERNAME.format(name=name))
        return

    # enforce the bot-count limit here too (the Mini App cannot see it)
    user = await repo.get_user(user_id)
    bots = await repo.list_user_bots(user_id)
    is_pro = repo.is_pro_row(user)
    max_bots = config.PRO_MAX_BOTS if is_pro else config.FREE_MAX_BOTS
    if len(bots) >= max_bots:
        await message.answer(
            texts.BOT_LIMIT_REACHED.format(max=max_bots),
            reply_markup=keyboards.back_to_menu(),
        )
        return

    store.set(user_id, Dialog(action="create:token", text=f"{name}\n{username}"))
    await message.answer(
        texts.CREATE_BOT_ASK_TOKEN_AFTER_FORM.format(name=name, username=username),
        disable_web_page_preview=True,
    )


# ------------------------------------------------------------------ token + launch
@router.message(Dialog.action_filter("create:token"))
async def msg_token(message: Message) -> None:
    user_id = message.from_user.id
    d = store.get(user_id)
    if not d or not d.text:
        await message.answer(texts.DIALOG_EXPIRED)
        return

    # split "name\nusername" packed in dialog.text
    parts = d.text.split("\n", 1)
    intended_name = parts[0] if parts else ""
    intended_username = parts[1] if len(parts) > 1 else ""

    token = (message.text or "").strip()
    m = TOKEN_RE.search(token)
    if not m:
        await message.answer(texts.INVALID_TOKEN)
        return
    token = m.group(0)

    # validate via getMe using a temporary Bot instance
    from aiogram import Bot

    temp = Bot(token=token)
    try:
        me = await temp.get_me()
    except TelegramUnauthorizedError:
        # 401 from Telegram: really an invalid token
        await message.answer(texts.INVALID_TOKEN)
        return
    except TelegramNetworkError:
        # connectivity issue, not the user's fault — token is NOT rejected
        await message.answer(texts.TOKEN_CHECK_FAILED)
        return
    finally:
        await temp.session.close()

    username = (me.username or "").lower()
    title = me.first_name or intended_name or "My Bot"

    existing = await repo.get_bot_by_token(token)
    if existing:
        await message.answer("⚠️ این ربات قبلاً ثبت شده است!")
        store.pop(user_id)
        return

    # gentle warning if the created bot does not match what the user entered in
    # the form — we still launch it, but tell the user so they can fix it.
    mismatch_note = ""
    if intended_username and username and username != intended_username:
        mismatch_note = (
            f"\n\n⚠️ <b>توجه:</b> یوزرنیم رباتی که ساختی (<code>@{username}</code>) با "
            f"یوزرنیمی که توی فرم وارد کردی (<code>@{intended_username}</code>) فرق داره. "
            f"اشکالی نداره، ولی برای دفعات بعد دقت کن."
        )

    bot_id = await repo.create_bot(user_id, token, username, title)
    store.pop(user_id)

    await manager.start_bot_task(bot_id)
    await message.answer(
        texts.BOT_CREATED.format(title=title, username=username) + mismatch_note,
        disable_web_page_preview=True,
        reply_markup=keyboards.after_create_keyboard(),
    )
