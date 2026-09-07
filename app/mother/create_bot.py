"""Modern create-bot flow using Telegram's native "Managed Bots" feature.

How it works (this is the native Telegram modal from the screenshot):
1. The mother bot's owner enables "Bot Management Mode" on the mother bot via
   @BotFather (one-time setup).
2. User taps «🛠 ساخت ربات جدید» -> we show a button whose URL is
   ``https://t.me/newbot/{mother_username}/{suggested_username}?name={name}``.
3. Tapping that button opens Telegram's NATIVE "Create Bot" modal (the
   screenshot) where the user enters/edits the bot name + username and taps
   «Create».
4. Telegram creates the bot on the user's behalf and sends a ``managed_bot``
   update to the mother bot. The update carries a ``ManagedBotUpdated`` object
   with ``user`` (the creator) and ``bot_user`` (the new bot).
5. We call ``bot.get_managed_bot_token(user_id=bot_user.id)`` to fetch the new
   bot's token, persist it, and start polling.

A manual token-entry fallback (``bot:create:token``) is kept for users whose
mother bot does not yet have Bot Management Mode enabled.
"""

from __future__ import annotations

import logging
import re

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramUnauthorizedError, TelegramNetworkError
from aiogram.types import CallbackQuery, ManagedBotUpdated, Message

from .. import config, keyboards, repo, texts
from ..child import manager
from ..states import Dialog, store

log = logging.getLogger("mother:create")
router = Router(name="mother:create")

# Telegram tokens: <bot_id>:<secret>. No trailing \b — a token may legitimately
# end with "-" or "_" which \b would reject.
TOKEN_RE = re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{30,}")


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


# ------------------------------------------------------------------ intro
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
    # use the cached mother bot username if available; otherwise try to fetch it
    mother_username = config.MOTHER_BOT_USERNAME or await manager.bootstrap_mother()
    await cb.message.edit_text(
        texts.CREATE_BOT_INTRO,
        reply_markup=keyboards.create_bot_intro_keyboard(mother_username),
        disable_web_page_preview=True,
    )


# ------------------------------------------------------------------ native flow: ask name -> ask username -> show native button
@router.callback_query(F.data == "bot:create:native")
async def cb_create_native(cb: CallbackQuery) -> None:
    """Start the modern native-modal flow: ask for the bot name first."""
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

    mother_username = config.MOTHER_BOT_USERNAME or await manager.bootstrap_mother()
    if not mother_username:
        await message.answer(texts.CREATE_BOT_NO_USERNAME)
        return

    store.pop(message.from_user.id)
    await message.answer(
        texts.CREATE_BOT_OPEN_NATIVE_MODAL.format(name=name, username=username),
        reply_markup=keyboards.create_bot_native_keyboard(mother_username, username, name),
        disable_web_page_preview=True,
    )


# ------------------------------------------------------------------ managed_bot update handler
@router.managed_bot()
async def on_managed_bot(event: ManagedBotUpdated, bot: Bot) -> None:
    """Native Telegram "Create Bot" confirmation arrives here.

    Telegram sends this update when a user completes the native Create-Bot
    modal opened via ``https://t.me/newbot/{mother_username}/...``. The
    ``event`` (a ManagedBotUpdated) carries:
      - ``user``: the User that created the bot (the owner)
      - ``bot_user``: information about the new bot (User object)
    We fetch the new bot's token via ``getManagedBotToken`` and launch it.
    """
    creator = event.user
    new_bot_user = event.bot_user
    if not creator or not new_bot_user:
        log.warning("managed_bot update without user/bot_user: %r", event)
        return

    owner_id = creator.id
    new_bot_id = new_bot_user.id
    new_bot_username = (new_bot_user.username or "").lower()
    new_bot_title = new_bot_user.first_name or "My Bot"

    log.info(
        "managed_bot update: creator=%d created bot id=%d @%s",
        owner_id, new_bot_id, new_bot_username or "?",
    )

    # enforce the bot-count limit on the creator's account
    user = await repo.get_user(owner_id)
    if not user:
        # the creator must already be a registered user (UserMiddleware runs
        # on message/cb updates; managed_bot is a different update type so we
        # register them here if missing)
        await repo.upsert_user(owner_id, creator.first_name, creator.username)
        user = await repo.get_user(owner_id)
    bots = await repo.list_user_bots(owner_id)
    is_pro = repo.is_pro_row(user)
    max_bots = config.PRO_MAX_BOTS if is_pro else config.FREE_MAX_BOTS
    if len(bots) >= max_bots:
        await manager.notify_user(
            owner_id,
            texts.BOT_LIMIT_REACHED.format(max=max_bots),
        )
        return

    # fetch the new bot's token via the Managed Bots API
    try:
        token = await bot.get_managed_bot_token(user_id=new_bot_id)
    except Exception as e:
        log.error("getManagedBotToken failed for bot %d: %r", new_bot_id, e)
        await manager.notify_user(
            owner_id,
            "⚠️ ربات ساخته شد ولی گرفتن توکنش ناموفق بود. لطفاً با پشتیبانی در تماس باش.",
        )
        return

    if not token or not isinstance(token, str):
        log.error("getManagedBotToken returned no token for bot %d", new_bot_id)
        return

    # avoid duplicates (the same managed_bot update can theoretically arrive twice)
    existing = await repo.get_bot_by_token(token)
    if existing:
        log.info("managed bot %d already registered (token exists)", new_bot_id)
        return

    bot_id = await repo.create_bot(owner_id, token, new_bot_username, new_bot_title)
    await manager.start_bot_task(bot_id)
    log.info("managed bot #%d (@%s) registered & started", bot_id, new_bot_username)

    await manager.notify_user(
        owner_id,
        texts.BOT_CREATED_VIA_MANAGED.format(
            title=new_bot_title, username=new_bot_username or new_bot_id
        ),
    )


# ------------------------------------------------------------------ manual token fallback
@router.callback_query(F.data == "bot:create:token")
async def cb_create_token(cb: CallbackQuery) -> None:
    """Old-school manual token flow — kept as a fallback."""
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

    store.set(cb.from_user.id, Dialog(action="create:token:manual"))
    await cb.answer()
    await cb.message.edit_text(texts.CREATE_BOT_ASK_TOKEN, disable_web_page_preview=True)


@router.message(Dialog.action_filter("create:token:manual"))
async def msg_manual_token(message: Message) -> None:
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
    except TelegramUnauthorizedError:
        await message.answer(texts.INVALID_TOKEN)
        return
    except TelegramNetworkError:
        await message.answer(texts.TOKEN_CHECK_FAILED)
        return
    finally:
        await temp.session.close()

    username = (me.username or "").lower()
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
        reply_markup=keyboards.after_create_keyboard(),
    )
