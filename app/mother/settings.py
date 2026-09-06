"""Bot settings: name, photo, bio, description, knowledge, channels, model, stats, delete."""

from __future__ import annotations

import io
import re

from aiogram import F, Router
from aiogram.types import BufferedInputFile, CallbackQuery, InputProfilePhotoStatic, Message

from .. import config, keyboards, repo, texts
from ..child import manager
from ..states import Dialog, store

router = Router(name="mother:settings")

_USERNAME_RE = re.compile(r"^@?([A-Za-z0-9_]{4,32})$")
_INVITE_RE = re.compile(
    r"(?:t\.me|telegram\.me)/(?:\+|joinchat/)([A-Za-z0-9_-]{8,64})", re.IGNORECASE
)
_LINK_RE = re.compile(r"(?:t\.me|telegram\.me)/@?([A-Za-z0-9_]{4,32})", re.IGNORECASE)


def _fmt_channel(c: str) -> str:
    return c if c.startswith("+") else f"@{c}"


def _parse_channel(raw: str) -> str | None:
    """Accept @username, t.me/username, t.me/+invite or t.me/joinchat/xxx links.

    (The old code had `... or "telegram.me/+" ...` — a truthy constant — which
    made the branch always match and ANY random text was accepted as a channel.)
    """
    raw = (raw or "").strip()
    if not raw:
        return None
    m = _USERNAME_RE.match(raw)
    if m:
        return m.group(1)
    m = _INVITE_RE.search(raw)
    if m:
        return "+" + m.group(1)
    m = _LINK_RE.search(raw)
    if m:
        return m.group(1)
    return None


async def _get_own_bot(cb: CallbackQuery, bot_id: int):
    row = await repo.get_bot(bot_id)
    if not row or row["owner_id"] != cb.from_user.id:
        await cb.answer("⛔ این ربات متعلق به شما نیست!", show_alert=True)
        return None
    return row


async def _open_settings(cb: CallbackQuery, bot_id: int) -> None:
    row = await repo.get_bot(bot_id)
    if not row or row["owner_id"] != cb.from_user.id:
        await cb.answer("⛔ این ربات متعلق به شما نیست!", show_alert=True)
        return

    if not row["knowledge"]:
        knowledge_status = "❌ ثبت نشده"
    else:
        knowledge_status = f"✅ {len(row['knowledge'])} کاراکتر"
    channels = "، ".join(_fmt_channel(c) for c in row["channels"]) or "—"
    model = config.SUPPORTED_MODELS.get(row["model"] or "", "پیش‌فرض (GPT)")
    biz_status = "ℹ️ طبق راهنما فعال کن" if not row["welcome_message"] else "ℹ️ طبق راهنما"

    if not cb.message:
        await cb.answer()
        return
    await cb.message.edit_text(
        texts.SETTINGS_MENU.format(
            username=row["username"] or row["id"],
            title=row["title"] or "—",
            knowledge_status=knowledge_status,
            channels=channels,
            model=model,
            biz_status=biz_status,
        ),
        reply_markup=keyboards.bot_settings_keyboard(row),
    )


@router.callback_query(F.data.startswith("bot:open:"))
async def cb_open_bot(cb: CallbackQuery) -> None:
    bot_id = int(cb.data.split(":")[2])
    store.pop(cb.from_user.id)
    await _open_settings(cb, bot_id)


# ------------------------------------------------------------------ simple text setters
async def _ask_text(cb: CallbackQuery, action: str, prompt: str, bot_id: int) -> None:
    store.set(cb.from_user.id, Dialog(action=action, bot_id=bot_id))
    if not cb.message:
        await cb.answer()
        return
    await cb.answer()
    await cb.message.edit_text(prompt)


@router.callback_query(F.data.startswith("set:title:"))
async def cb_set_title(cb: CallbackQuery) -> None:
    bot_id = int(cb.data.split(":")[2])
    if not await _get_own_bot(cb, bot_id):
        return
    await _ask_text(cb, "set:title", texts.ASK_NEW_TITLE, bot_id)


@router.callback_query(F.data.startswith("set:bio:"))
async def cb_set_bio(cb: CallbackQuery) -> None:
    bot_id = int(cb.data.split(":")[2])
    if not await _get_own_bot(cb, bot_id):
        return
    await _ask_text(cb, "set:bio", texts.ASK_NEW_BIO, bot_id)


@router.callback_query(F.data.startswith("set:desc:"))
async def cb_set_desc(cb: CallbackQuery) -> None:
    bot_id = int(cb.data.split(":")[2])
    if not await _get_own_bot(cb, bot_id):
        return
    await _ask_text(cb, "set:desc", texts.ASK_NEW_DESCRIPTION, bot_id)


@router.callback_query(F.data.startswith("set:knowledge:"))
async def cb_set_knowledge(cb: CallbackQuery) -> None:
    bot_id = int(cb.data.split(":")[2])
    row = await _get_own_bot(cb, bot_id)
    if not row:
        return
    owner = await repo.get_user(cb.from_user.id)
    is_pro = repo.is_pro_row(owner)
    limit = config.PRO_KNOWLEDGE_CHARS if is_pro else config.FREE_KNOWLEDGE_CHARS
    store.set(cb.from_user.id, Dialog(action="set:knowledge", bot_id=bot_id))
    if not cb.message:
        await cb.answer()
        return
    await cb.answer()
    await cb.message.edit_text(
        texts.ASK_KNOWLEDGE.format(limit=limit, current=len(row["knowledge"])),
    )


@router.callback_query(F.data.startswith("set:welcome:"))
async def cb_set_welcome(cb: CallbackQuery) -> None:
    bot_id = int(cb.data.split(":")[2])
    row = await _get_own_bot(cb, bot_id)
    if not row:
        return
    owner = await repo.get_user(cb.from_user.id)
    if not repo.is_pro_row(owner):
        await cb.answer(texts.NEED_PRO, show_alert=True)
        return
    store.set(cb.from_user.id, Dialog(action="set:welcome", bot_id=bot_id))
    if not cb.message:
        await cb.answer()
        return
    await cb.answer()
    await cb.message.edit_text(texts.ASK_WELCOME)


@router.callback_query(F.data.startswith("set:model:"))
async def cb_set_model(cb: CallbackQuery) -> None:
    bot_id = int(cb.data.split(":")[2])
    row = await _get_own_bot(cb, bot_id)
    if not row:
        return
    owner = await repo.get_user(cb.from_user.id)
    is_pro = repo.is_pro_row(owner)
    models = config.PRO_MODELS + config.FREE_MODELS if is_pro else config.FREE_MODELS
    if not cb.message:
        await cb.answer()
        return
    await cb.answer()
    await cb.message.edit_text(
        texts.SELECT_MODEL,
        reply_markup=keyboards.model_keyboard(bot_id, models, row["model"]),
    )


@router.callback_query(F.data.startswith("model:"))
async def cb_model_pick(cb: CallbackQuery) -> None:
    parts = cb.data.split(":")
    bot_id, model = int(parts[1]), parts[2]
    row = await _get_own_bot(cb, bot_id)
    if not row:
        return
    owner = await repo.get_user(cb.from_user.id)
    is_pro = repo.is_pro_row(owner)
    allowed = config.PRO_MODELS + config.FREE_MODELS if is_pro else config.FREE_MODELS
    if model not in allowed:
        await cb.answer(texts.NEED_PRO, show_alert=True)
        return
    await repo.set_bot_model(bot_id, model)
    await cb.answer()
    if not cb.message:
        return
    await cb.message.edit_text(
        texts.MODEL_SAVED.format(model=config.SUPPORTED_MODELS.get(model, model)),
        reply_markup=keyboards.back_to_bot(bot_id),
    )


@router.callback_query(F.data.startswith("set:stats:"))
async def cb_set_stats(cb: CallbackQuery) -> None:
    bot_id = int(cb.data.split(":")[2])
    row = await _get_own_bot(cb, bot_id)
    if not row:
        return
    owner = await repo.get_user(cb.from_user.id)
    if not repo.is_pro_row(owner):
        await cb.answer()
        if cb.message:
            await cb.message.answer(texts.STATS_NOT_PRO, reply_markup=keyboards.back_to_bot(bot_id))
        return
    messages = await repo.month_usage_total(bot_id)
    chats = await repo.month_unique_chats(bot_id)
    await cb.answer()
    if cb.message:
        await cb.message.answer(
            texts.STATS_TEXT.format(
                username=row["username"] or bot_id,
                messages=messages,
                chats=chats,
                knowledge=len(row["knowledge"]),
            ),
            reply_markup=keyboards.back_to_bot(bot_id),
        )


# ------------------------------------------------------------------ photos
@router.callback_query(F.data.startswith("set:photo:"))
async def cb_set_photo(cb: CallbackQuery) -> None:
    parts = cb.data.split(":")
    if len(parts) == 4 and parts[2] == "del":
        bot_id = int(parts[3])
        row = await _get_own_bot(cb, bot_id)
        if not row:
            return
        child = manager.get_api_bot(bot_id, row["token"])
        try:
            await child.remove_my_profile_photo()
            await cb.answer(texts.PHOTO_REMOVED)
        except Exception:
            await cb.answer(texts.SET_FAIL, show_alert=True)
        return

    bot_id = int(parts[2])
    if not await _get_own_bot(cb, bot_id):
        return
    store.set(cb.from_user.id, Dialog(action="set:photo", bot_id=bot_id))
    if not cb.message:
        await cb.answer()
        return
    await cb.answer()
    await cb.message.edit_text(texts.ASK_PROFILE_PHOTO, reply_markup=keyboards.photo_keyboard(bot_id))


@router.callback_query(F.data.startswith("set:descphoto:"))
async def cb_set_descphoto(cb: CallbackQuery) -> None:
    # The Bot API has no direct method for the "description photo" (the image
    # shown above the description page). BotFather-only feature -> we explain.
    bot_id = int(cb.data.split(":")[2])
    if not await _get_own_bot(cb, bot_id):
        return
    if not cb.message:
        await cb.answer()
        return
    await cb.answer()
    await cb.message.edit_text(
        "🖼 <b>عکس توضیحات (Description Picture)</b>\n\n"
        "این عکس بالای صفحه توضیحات ربات نمایش داده می‌شه.\n\n"
        "⚠️ تلگرام فعلاً فقط از طریق <b>@BotFather</b> اجازه تغییر این عکس رو می‌ده:\n"
        "۱️⃣ به <code>@BotFather</code> پیام بده\n"
        "۲️⃣ <code>/mybots</code> ← انتخاب ربات\n"
        "۳️⃣ <b>Edit Bot</b> ← <b>Edit Description Picture</b>\n"
        "۴️⃣ عکس مورد نظرت رو بفرست\n\n"
        "بقیه تنظیمات (اسم، عکس پروفایل، بیو، توضیحات) همین‌جا قابل تغییره ✅",
        reply_markup=keyboards.back_to_bot(bot_id),
    )


# ------------------------------------------------------------------ channel management
@router.callback_query(F.data.startswith("set:channels:"))
async def cb_set_channels(cb: CallbackQuery) -> None:
    bot_id = int(cb.data.split(":")[2])
    row = await _get_own_bot(cb, bot_id)
    if not row:
        return
    owner = await repo.get_user(cb.from_user.id)
    is_pro = repo.is_pro_row(owner)
    limit = config.PRO_CHANNEL_LIMIT if is_pro else config.FREE_CHANNEL_LIMIT
    can_add = len(row["channels"]) < limit
    if not cb.message:
        await cb.answer()
        return
    await cb.answer()
    await cb.message.edit_text(
        texts.ASK_CHANNEL.format(
            channels="، ".join(_fmt_channel(c) for c in row["channels"]) or "—"
        ),
        reply_markup=keyboards.channels_keyboard(row, can_add),
    )


@router.callback_query(F.data.startswith("ch:add:"))
async def cb_channel_add(cb: CallbackQuery) -> None:
    bot_id = int(cb.data.split(":")[2])
    row = await _get_own_bot(cb, bot_id)
    if not row:
        return
    store.set(cb.from_user.id, Dialog(action="ch:add", bot_id=bot_id))
    if not cb.message:
        await cb.answer()
        return
    await cb.answer()
    await cb.message.edit_text(
        texts.ASK_CHANNEL.format(
            channels="، ".join(_fmt_channel(c) for c in row["channels"]) or "—"
        )
    )


@router.callback_query(F.data.startswith("ch:del:"))
async def cb_channel_del(cb: CallbackQuery) -> None:
    parts = cb.data.split(":")
    bot_id, idx = int(parts[2]), int(parts[3])
    row = await _get_own_bot(cb, bot_id)
    if not row:
        return
    channels = row["channels"] or []
    if 0 <= idx < len(channels):
        await repo.remove_bot_channel(bot_id, channels[idx])
        await cb.answer(texts.CHANNEL_REMOVED)
    else:
        await cb.answer()
    row = await repo.get_bot(bot_id)
    if not row or not cb.message:
        return
    owner = await repo.get_user(cb.from_user.id)
    is_pro = repo.is_pro_row(owner)
    limit = config.PRO_CHANNEL_LIMIT if is_pro else config.FREE_CHANNEL_LIMIT
    await cb.message.edit_text(
        texts.ASK_CHANNEL.format(
            channels="، ".join(_fmt_channel(c) for c in row["channels"]) or "—"
        ),
        reply_markup=keyboards.channels_keyboard(row, len(row["channels"]) < limit),
    )


@router.callback_query(F.data.startswith("set:business:"))
async def cb_set_business(cb: CallbackQuery) -> None:
    bot_id = int(cb.data.split(":")[2])
    if not await _get_own_bot(cb, bot_id):
        return
    if not cb.message:
        await cb.answer()
        return
    await cb.answer()
    await cb.message.edit_text(
        texts.BUSINESS_GUIDE, reply_markup=keyboards.back_to_bot(bot_id)
    )


# ------------------------------------------------------------------ delete bot
@router.callback_query(F.data.startswith("bot:del:yes:"))
async def cb_delete_yes(cb: CallbackQuery) -> None:
    bot_id = int(cb.data.split(":")[3])
    row = await _get_own_bot(cb, bot_id)
    if not row:
        return
    manager.stop_bot_task(bot_id)
    await repo.delete_bot(bot_id)
    await cb.answer("🗑 ربات حذف شد")
    if cb.message:
        await cb.message.edit_text("🗑 ربات حذف شد.", reply_markup=keyboards.back_to_menu())


@router.callback_query(F.data.startswith("bot:del:"))
async def cb_delete_ask(cb: CallbackQuery) -> None:
    bot_id = int(cb.data.split(":")[2])
    if not await _get_own_bot(cb, bot_id):
        return
    if not cb.message:
        await cb.answer()
        return
    await cb.answer()
    await cb.message.edit_text(
        "⚠️ مطمئنی می‌خوای این ربات رو حذف کنی؟\n\n"
        "همه دانش و تنظیماتش پاک می‌شه و ربات دیگه جواب نمی‌ده!",
        reply_markup=keyboards.delete_confirm_keyboard(bot_id),
    )


# ------------------------------------------------------------------ dialog text input
async def _expired(message: Message) -> bool:
    """Dialog vanished (TTL or restart) — tell the user instead of ignoring."""
    await message.answer(texts.DIALOG_EXPIRED)
    return True


@router.message(Dialog.action_filter("set:photo"))
async def msg_photo(message: Message) -> None:
    d = store.get(message.from_user.id)
    if not d:
        await _expired(message)
        return
    row = await repo.get_bot(d.bot_id)
    if not row:
        store.pop(message.from_user.id)
        await message.answer(texts.GENERIC_ERROR)
        return
    if not message.photo:
        # keep the dialog alive so the user can retry with a proper photo
        await message.answer("⚠️ لطفاً عکس رو به‌صورت <b>عکس</b> بفرست، نه فایل!")
        return

    file_id = message.photo[-1].file_id
    mother = message.bot
    tg_file = await mother.get_file(file_id)
    buf = io.BytesIO()
    await mother.download_file(tg_file.file_path, destination=buf)
    buf.seek(0)

    child = manager.get_api_bot(d.bot_id, row["token"])
    try:
        # profile photos must be uploaded as new files (file_id reuse not allowed)
        photo_input = InputProfilePhotoStatic(
            type="static", photo=BufferedInputFile(buf.getvalue(), filename="avatar.jpg")
        )
        await child.set_my_profile_photo(photo=photo_input)
        store.pop(message.from_user.id)
        await message.answer(texts.PHOTO_SET_OK)
    except Exception:
        await message.answer(texts.SET_FAIL)


@router.message(Dialog.action_filter("set:title"))
async def msg_title(message: Message) -> None:
    d = store.get(message.from_user.id)
    if not d:
        await _expired(message)
        return
    row = await repo.get_bot(d.bot_id)
    title = (message.text or "").strip()
    if not (1 <= len(title) <= 64):
        await message.answer(texts.TITLE_LENGTH)
        return
    child = manager.get_api_bot(d.bot_id, row["token"]) if row else None
    if not child:
        store.pop(message.from_user.id)
        await message.answer(texts.GENERIC_ERROR)
        return
    try:
        await child.set_my_name(title)
        await repo.set_bot_title(d.bot_id, title)
        store.pop(message.from_user.id)
        await message.answer(texts.SET_OK)
    except Exception:
        await message.answer(texts.SET_FAIL)


@router.message(Dialog.action_filter("set:bio"))
async def msg_bio(message: Message) -> None:
    d = store.get(message.from_user.id)
    if not d:
        await _expired(message)
        return
    row = await repo.get_bot(d.bot_id)
    bio = (message.text or "").strip()
    if not (1 <= len(bio) <= 120):
        await message.answer(texts.BIO_LENGTH)
        return
    child = manager.get_api_bot(d.bot_id, row["token"]) if row else None
    if not child:
        store.pop(message.from_user.id)
        await message.answer(texts.GENERIC_ERROR)
        return
    try:
        await child.set_my_short_description(bio)
        store.pop(message.from_user.id)
        await message.answer(texts.SET_OK)
    except Exception:
        await message.answer(texts.SET_FAIL)


@router.message(Dialog.action_filter("set:desc"))
async def msg_desc(message: Message) -> None:
    d = store.get(message.from_user.id)
    if not d:
        await _expired(message)
        return
    row = await repo.get_bot(d.bot_id)
    desc = (message.text or "").strip()
    if not (1 <= len(desc) <= 512):
        await message.answer(texts.DESC_LENGTH)
        return
    child = manager.get_api_bot(d.bot_id, row["token"]) if row else None
    if not child:
        store.pop(message.from_user.id)
        await message.answer(texts.GENERIC_ERROR)
        return
    try:
        await child.set_my_description(desc)
        store.pop(message.from_user.id)
        await message.answer(texts.SET_OK)
    except Exception:
        await message.answer(texts.SET_FAIL)


@router.message(Dialog.action_filter("set:knowledge"))
async def msg_knowledge(message: Message) -> None:
    d = store.get(message.from_user.id)
    if not d:
        await _expired(message)
        return
    row = await repo.get_bot(d.bot_id)
    if not row:
        store.pop(message.from_user.id)
        await message.answer(texts.GENERIC_ERROR)
        return
    owner = await repo.get_user(message.from_user.id)
    is_pro = repo.is_pro_row(owner)
    limit = config.PRO_KNOWLEDGE_CHARS if is_pro else config.FREE_KNOWLEDGE_CHARS
    text = (message.text or "").strip()
    if not text:
        await message.answer("⚠️ متن خالی قابل ذخیره نیست!")
        return
    if len(text) > limit:
        await message.answer(
            f"⚠️ متن خیلی طولانیه! حداکثر {limit} کاراکتر مجاز است "
            f"(متن شما {len(text)} کاراکتر بود)."
        )
        return
    await repo.set_bot_knowledge(d.bot_id, text)
    store.pop(message.from_user.id)
    await message.answer(texts.KNOWLEDGE_SAVED)


@router.message(Dialog.action_filter("set:welcome"))
async def msg_welcome(message: Message) -> None:
    d = store.get(message.from_user.id)
    if not d:
        await _expired(message)
        return
    owner = await repo.get_user(message.from_user.id)
    if not repo.is_pro_row(owner):
        store.pop(message.from_user.id)
        await message.answer(texts.NEED_PRO)
        return
    text = (message.text or "").strip()
    if len(text) > 1000:
        await message.answer("⚠️ پیام خیلی طولانیه! حداکثر ۱۰۰۰ کاراکتر.")
        return
    await repo.set_bot_welcome(d.bot_id, text or None)
    store.pop(message.from_user.id)
    await message.answer(texts.WELCOME_SAVED)


@router.message(Dialog.action_filter("ch:add"))
async def msg_channel_add(message: Message) -> None:
    d = store.get(message.from_user.id)
    if not d:
        await _expired(message)
        return
    row = await repo.get_bot(d.bot_id)
    if not row:
        store.pop(message.from_user.id)
        await message.answer(texts.GENERIC_ERROR)
        return

    channel = _parse_channel(message.text or "")
    if not channel:
        # keep the dialog alive for retry
        await message.answer(texts.CHANNEL_INVALID)
        return

    owner = await repo.get_user(message.from_user.id)
    is_pro = repo.is_pro_row(owner)
    limit = config.PRO_CHANNEL_LIMIT if is_pro else config.FREE_CHANNEL_LIMIT
    if len(row["channels"]) >= limit:
        store.pop(message.from_user.id)
        await message.answer(texts.CHANNEL_LIMIT.format(max=limit))
        return

    await repo.add_bot_channel(d.bot_id, channel)
    store.pop(message.from_user.id)
    await message.answer(texts.CHANNEL_ADDED)
