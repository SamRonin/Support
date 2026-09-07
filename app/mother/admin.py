"""Owner admin panel — full visibility & control over the whole bot farm.

Access: ``/admin`` command or the «🛡 پنل مدیریت» button (ADMIN_ID only).

Sections:
- Dashboard   : users / bots / payments / revenue / AI usage stats (one query)
- Users       : paginated list, user detail, grant or revoke Pro, ban/unban,
                per-user payments & usage, referral stats
- Bots        : every child bot with its owner, model, knowledge size,
                monthly usage, error count — turn on/off or delete
- Payments    : all purchase requests with filters; approve (auto-grants Pro
                and notifies the buyer) or reject — same logic as the channel
- Broadcast   : send one message to every non-banned user (rate-limited)
- Search      : find a user by numeric ID or @username

All admin callbacks use the unique ``adm:`` prefix so they cannot collide
with the regular user flows. Handlers with more specific prefixes must be
registered before the generic ones (aiogram checks in order).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import html
import logging

from aiogram import F, Router
from aiogram.filters import BaseFilter, Command
from aiogram.types import CallbackQuery, Message

from .. import config, keyboards, repo, texts
from ..child import handlers as child_handlers
from ..child import manager
from ..states import Dialog, store

log = logging.getLogger("mother:admin")

router = Router(name="mother:admin")

USERS_PAGE = 8
BOTS_PAGE = 8
PAYS_PAGE = 6

_BROADCAST_INTERVAL = 0.04  # ~25 msg/s — safely under Telegram's ~30/s limit
_FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

_PAY_STATUS_ICON = {"pending": "⏳", "approved": "✅", "rejected": "❌"}
_PAY_STATUS_FA = {
    "pending": "در انتظار بررسی",
    "approved": "تاییدشده",
    "rejected": "ردشده",
}


class AdminFilter(BaseFilter):
    """Only the configured ADMIN_ID passes."""

    async def __call__(self, event) -> bool:
        return config.is_admin(event.from_user.id)


# ------------------------------------------------------------------ helpers
def _fmt_dt(value) -> str:
    if not value:
        return "—"
    if isinstance(value, str):
        return value[:16].replace("T", " ")
    return value.strftime("%Y-%m-%d %H:%M")


def _fmt_date(value) -> str:
    if not value:
        return "—"
    if isinstance(value, str):
        return value[:10]
    return value.strftime("%Y-%m-%d")


def _int_maybe(raw: str) -> int | None:
    """Parse digits (Persian or Latin) -> int; None when invalid."""
    raw = (raw or "").strip().translate(_FA_DIGITS)
    if not raw.isdigit():
        return None
    return int(raw)


def _pages(total: int, per_page: int) -> int:
    return max(1, (total + per_page - 1) // per_page)


async def _edit_or_answer(cb: CallbackQuery, text: str, reply_markup=None) -> None:
    """Panel renderer: edit the panel message, or send a new one when the
    original cannot be edited (e.g. too old)."""
    if cb.message is None:
        await cb.answer()
        return
    try:
        await cb.message.edit_text(text, reply_markup=reply_markup)
    except Exception:
        try:
            await cb.message.answer(text, reply_markup=reply_markup)
        except Exception:
            pass


# ------------------------------------------------------------------ dashboard
def _dashboard_text(stats: dict) -> str:
    return texts.ADMIN_DASHBOARD.format(
        users_total=stats.get("users_total", 0),
        users_today=stats.get("users_today", 0),
        users_week=stats.get("users_week", 0),
        users_pro=stats.get("users_pro", 0),
        users_banned=stats.get("users_banned", 0),
        bots_total=stats.get("bots_total", 0),
        bots_active=stats.get("bots_active", 0),
        bots_off=stats.get("bots_total", 0) - stats.get("bots_active", 0),
        pays_pending=stats.get("pays_pending", 0),
        pays_approved=stats.get("pays_approved", 0),
        pays_rejected=stats.get("pays_rejected", 0),
        revenue=stats.get("revenue", 0) or 0,
        usage_month=stats.get("usage_month", 0) or 0,
        referrals_total=stats.get("referrals_total", 0),
    )


@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    if not config.is_admin(message.from_user.id):
        await message.answer(texts.ADMIN_ONLY)
        return
    stats = await repo.admin_stats()
    await message.answer(_dashboard_text(stats), reply_markup=keyboards.admin_main_keyboard())


@router.callback_query(F.data == "adm:menu", AdminFilter())
async def cb_admin_menu(cb: CallbackQuery) -> None:
    store.pop(cb.from_user.id)
    await cb.answer()
    stats = await repo.admin_stats()
    await _edit_or_answer(cb, _dashboard_text(stats), keyboards.admin_main_keyboard())


# ------------------------------------------------------------------ users
async def _render_user_detail(cb: CallbackQuery, user_id: int) -> None:
    user = await repo.get_user(user_id)
    if not user:
        await cb.answer(texts.ADMIN_USER_NOT_FOUND, show_alert=True)
        return
    bots = await repo.list_user_bots(user_id)
    pays = await repo.user_payments(user_id)
    usage = await repo.user_usage_month(user_id)
    referrals = await repo.count_referrals(user_id)

    if repo.is_pro_row(user):
        plan = texts.PLAN_PRO.format(date=_fmt_date(user["pro_until"]))
    else:
        plan = "🆓 رایگان"
    uname = f" — @{user['username']}" if user.get("username") else ""
    bots_line = ""
    if bots:
        listed = "، ".join(
            f"@{b['username'] or b['id']}" + ("" if b["active"] else " (⛔)") for b in bots[:5]
        )
        bots_line = "\n🤖 ربات‌های کاربر: " + listed
    pays_ok = sum(1 for p in pays if p["status"] == "approved")
    pays_pending = sum(1 for p in pays if p["status"] == "pending")

    text = texts.ADMIN_USER_DETAIL.format(
        name=html.escape(user.get("first_name") or "—"),
        username=uname,
        user_id=user["user_id"],
        plan=plan,
        banned="🚫 بله" if user.get("banned") else "خیر",
        bots=len(bots),
        usage=usage,
        pays_total=len(pays),
        pays_ok=pays_ok,
        pays_pending=pays_pending,
        referrals=referrals,
        created=_fmt_dt(user.get("created_at")),
        bots_line=bots_line,
    )
    await _edit_or_answer(cb, text, keyboards.admin_user_detail_keyboard(user))


async def _render_users(cb: CallbackQuery, page: int) -> None:
    total = await repo.count_users()
    pages = _pages(total, USERS_PAGE)
    page = max(0, min(page, pages - 1))
    users = await repo.list_users(page * USERS_PAGE, USERS_PAGE)

    rows = []
    for i, u in enumerate(users, start=1):
        badges = ""
        if keyboards.repo_is_pro(u):
            badges += " 💎"
        if u.get("banned"):
            badges += " 🚫"
        uname = f" — @{u['username']}" if u.get("username") else ""
        rows.append(f"{i}. {html.escape(u.get('first_name') or '—')}{uname} — <code>{u['user_id']}</code>{badges}")

    text = texts.ADMIN_USERS_TITLE.format(
        page=page + 1,
        pages=pages,
        total=total,
        rows="\n".join(rows) or "(بدون کاربر)",
    )
    await _edit_or_answer(cb, text, keyboards.admin_users_keyboard(users, page, pages))


@router.callback_query(F.data.startswith("adm:users:"), AdminFilter())
async def cb_admin_users(cb: CallbackQuery) -> None:
    await cb.answer()
    page = _int_maybe(cb.data.split(":")[2]) or 0
    await _render_users(cb, page)


# user detail (generic adm:u:<id> — AFTER all adm:u:<verb>: handlers)
@router.callback_query(F.data.startswith("adm:u:grant:"), AdminFilter())
async def cb_user_grant(cb: CallbackQuery) -> None:
    user_id = _int_maybe(cb.data.split(":")[3])
    user = await repo.get_user(user_id) if user_id else None
    if not user:
        await cb.answer(texts.ADMIN_USER_NOT_FOUND, show_alert=True)
        return
    store.set(cb.from_user.id, Dialog(action="admin:grant_pro", target_user_id=user_id))
    await cb.answer()
    if cb.message:
        await cb.message.edit_text(
            texts.ADMIN_GRANT_ASK.format(
                name=html.escape(user.get("first_name") or "—"), user_id=user_id
            ),
            reply_markup=keyboards.admin_grant_days_keyboard(user_id),
        )


@router.callback_query(F.data.startswith("adm:u:grantd:"), AdminFilter())
async def cb_user_grant_direct(cb: CallbackQuery) -> None:
    parts = cb.data.split(":")
    user_id, days = _int_maybe(parts[3]), _int_maybe(parts[4])
    if not user_id or not days:
        await cb.answer()
        return
    await _grant_pro(cb, user_id, days)


async def _grant_pro(cb: CallbackQuery, user_id: int, days: int) -> None:
    user = await repo.get_user(user_id)
    if not user:
        await cb.answer(texts.ADMIN_USER_NOT_FOUND, show_alert=True)
        return
    await repo.grant_pro(user_id, days)
    child_handlers.invalidate_owner_cache(user_id)
    await manager.notify_user(
        user_id,
        f"🎉 <b>اشتراک 💎 پرو از طرف مدیریت فعال شد!</b>\n\n"
        f"مدت: <b>{days} روز</b>\nاز همه امکانات پرو لذت ببر 🚀",
    )
    await cb.answer(f"✅ {days} روز پرو داده شد", show_alert=False)
    await _render_user_detail(cb, user_id)


@router.callback_query(F.data.startswith("adm:u:unpro:"), AdminFilter())
async def cb_user_unpro(cb: CallbackQuery) -> None:
    user_id = _int_maybe(cb.data.split(":")[3])
    if not user_id:
        await cb.answer()
        return
    await repo.revoke_pro(user_id)
    child_handlers.invalidate_owner_cache(user_id)
    await cb.answer("✅ پرو این کاربر حذف شد")
    await _render_user_detail(cb, user_id)


@router.callback_query(F.data.startswith("adm:u:ban:"), AdminFilter())
async def cb_user_ban(cb: CallbackQuery) -> None:
    user_id = _int_maybe(cb.data.split(":")[3])
    user = await repo.get_user(user_id) if user_id else None
    if not user:
        await cb.answer(texts.ADMIN_USER_NOT_FOUND, show_alert=True)
        return
    await cb.answer()
    if cb.message:
        await cb.message.edit_text(
            texts.ADMIN_BAN_CONFIRM.format(
                name=html.escape(user.get("first_name") or "—"), user_id=user_id
            ),
            reply_markup=keyboards.admin_ban_confirm_keyboard(user_id),
        )


@router.callback_query(F.data.startswith("adm:u:banyes:"), AdminFilter())
async def cb_user_ban_yes(cb: CallbackQuery) -> None:
    user_id = _int_maybe(cb.data.split(":")[3])
    if not user_id:
        await cb.answer()
        return
    await repo.set_banned(user_id, True)
    await cb.answer("🚫 کاربر بن شد")
    await _render_user_detail(cb, user_id)


@router.callback_query(F.data.startswith("adm:u:unban:"), AdminFilter())
async def cb_user_unban(cb: CallbackQuery) -> None:
    user_id = _int_maybe(cb.data.split(":")[3])
    if not user_id:
        await cb.answer()
        return
    await repo.set_banned(user_id, False)
    await cb.answer("✅ بن کاربر برداشته شد")
    await _render_user_detail(cb, user_id)


@router.callback_query(F.data.startswith("adm:u:pays:"), AdminFilter())
async def cb_user_pays(cb: CallbackQuery) -> None:
    user_id = _int_maybe(cb.data.split(":")[3])
    if not user_id:
        await cb.answer()
        return
    pays = await repo.user_payments(user_id)
    rows = []
    for p in pays:
        icon = _PAY_STATUS_ICON.get(p["status"], "❔")
        rows.append(
            f"{icon} <code>#{p['id']}</code> — {p['amount']:,} ت — "
            f"{_PAY_STATUS_FA.get(p['status'], p['status'])} — {_fmt_dt(p.get('decided_at') or p.get('created_at'))}"
        )
    user = await repo.get_user(user_id)
    name = html.escape((user or {}).get("first_name") or str(user_id))
    text = (
        f"💳 <b>خریدهای {name}</b> (<code>{user_id}</code>)\n\n"
        + ("\n".join(rows) if rows else "خریدی ثبت نشده.")
    )
    await cb.answer()
    await _edit_or_answer(cb, text, keyboards.admin_user_detail_keyboard(user or {"user_id": user_id}))


@router.callback_query(F.data.startswith("adm:u:"), AdminFilter())
async def cb_admin_user(cb: CallbackQuery) -> None:
    user_id = _int_maybe(cb.data.split(":")[2])
    if not user_id:
        await cb.answer(texts.GENERIC_ERROR, show_alert=True)
        return
    await cb.answer()
    await _render_user_detail(cb, user_id)


# ------------------------------------------------------------------ bots
async def _render_bot_detail(cb: CallbackQuery, bot_id: int) -> None:
    row = await repo.get_bot_with_owner(bot_id)
    if not row:
        await cb.answer(texts.GENERIC_ERROR, show_alert=True)
        return
    owner_uname = f"(@{row['owner_username']})" if row.get("owner_username") else ""
    text = texts.ADMIN_BOT_DETAIL.format(
        title=html.escape(row.get("title") or "—"),
        username=row.get("username") or "—",
        bot_id=row["id"],
        owner_name=html.escape(row.get("owner_first_name") or "—"),
        owner_username=owner_uname,
        owner_id=row["owner_id"],
        status="✅ فعال" if row["active"] else "⛔ غیرفعال",
        errors=row.get("error_count", 0),
        knowledge=len(row.get("knowledge") or ""),
        model=config.SUPPORTED_MODELS.get(row.get("model") or "", "پیش‌فرض (GPT)"),
        channels=len(row.get("channels") or []),
        usage=row.get("month_usage", 0) or 0,
        created=_fmt_dt(row.get("created_at")),
    )
    await _edit_or_answer(cb, text, keyboards.admin_bot_detail_keyboard(row))


async def _render_bots(cb: CallbackQuery, page: int) -> None:
    total = await repo.count_bots()
    pages = _pages(total, BOTS_PAGE)
    page = max(0, min(page, pages - 1))
    bots = await repo.list_all_bots(page * BOTS_PAGE, BOTS_PAGE)

    rows = []
    for i, b in enumerate(bots, start=1):
        status = "✅" if b["active"] else "⛔"
        owner = b.get("owner_username") or b.get("owner_first_name") or b["owner_id"]
        rows.append(
            f"{i}. {status} @{b['username'] or b['id']} — مالک: {html.escape(str(owner))} "
            f"— {b.get('month_usage', 0)} پیام"
        )
    text = texts.ADMIN_BOTS_TITLE.format(
        page=page + 1, pages=pages, total=total, rows="\n".join(rows) or "(رباتی نیست)"
    )
    await _edit_or_answer(cb, text, keyboards.admin_bots_keyboard(bots, page, pages))


@router.callback_query(F.data.startswith("adm:bots:"), AdminFilter())
async def cb_admin_bots(cb: CallbackQuery) -> None:
    await cb.answer()
    page = _int_maybe(cb.data.split(":")[2]) or 0
    await _render_bots(cb, page)


@router.callback_query(F.data.startswith("adm:b:on:"), AdminFilter())
async def cb_bot_on(cb: CallbackQuery) -> None:
    bot_id = _int_maybe(cb.data.split(":")[3])
    if not bot_id:
        await cb.answer()
        return
    await repo.set_bot_active(bot_id, True)
    await repo.reset_error_count(bot_id)
    manager.start_bot_task(bot_id)
    await cb.answer("✅ ربات روشن شد")
    await _render_bot_detail(cb, bot_id)


@router.callback_query(F.data.startswith("adm:b:off:"), AdminFilter())
async def cb_bot_off(cb: CallbackQuery) -> None:
    bot_id = _int_maybe(cb.data.split(":")[3])
    if not bot_id:
        await cb.answer()
        return
    await repo.set_bot_active(bot_id, False)
    manager.stop_bot_task(bot_id)
    await cb.answer("⛔ ربات خاموش شد")
    await _render_bot_detail(cb, bot_id)


@router.callback_query(F.data.startswith("adm:b:del:"), AdminFilter())
async def cb_bot_del_ask(cb: CallbackQuery) -> None:
    # NB: registered BEFORE the generic adm:b:<id> handler but the generic
    # one is "adm:b:" + int — "del" is not an int so parse order alone would
    # crash; explicit prefix handlers run first, which is why this works.
    bot_id = _int_maybe(cb.data.split(":")[3])
    row = await repo.get_bot_with_owner(bot_id) if bot_id else None
    if not row:
        await cb.answer(texts.GENERIC_ERROR, show_alert=True)
        return
    await cb.answer()
    if cb.message:
        await cb.message.edit_text(
            "⚠️ ربات <b>@{}</b> برای همیشه حذف بشه؟\n\n"
            "همه دانش و تنظیماتش پاک می‌شه و دیگه جواب نمی‌ده!".format(
                row.get("username") or row["id"]
            ),
            reply_markup=keyboards.admin_bot_delete_keyboard(bot_id),
        )


@router.callback_query(F.data.startswith("adm:b:delyes:"), AdminFilter())
async def cb_bot_del_yes(cb: CallbackQuery) -> None:
    # "adm:b:delyes:<id>" -> parts: adm / b / delyes / <id>
    bot_id = _int_maybe(cb.data.split(":")[3])
    if not bot_id:
        await cb.answer()
        return
    manager.stop_bot_task(bot_id)
    await repo.delete_bot(bot_id)
    await cb.answer("🗑 ربات حذف شد")
    await _render_bots(cb, 0)


@router.callback_query(F.data.startswith("adm:b:"), AdminFilter())
async def cb_admin_bot(cb: CallbackQuery) -> None:
    await cb.answer()
    bot_id = _int_maybe(cb.data.split(":")[2])
    if not bot_id:
        await cb.answer()
        return
    await _render_bot_detail(cb, bot_id)


# ------------------------------------------------------------------ payments
async def _render_payments(cb: CallbackQuery, flt: str, page: int) -> None:
    if flt not in ("pending", "approved", "rejected", "all"):
        flt = "all"
    status = None if flt == "all" else flt
    total = await repo.count_payments(status)
    pages = _pages(total, PAYS_PAGE)
    page = max(0, min(page, pages - 1))
    pays = await repo.list_payments(status, page * PAYS_PAGE, PAYS_PAGE)

    rows = []
    for p in pays:
        icon = _PAY_STATUS_ICON.get(p["status"], "❔")
        buyer = p.get("buyer_username") or p.get("buyer_name") or p["user_id"]
        rows.append(
            f"{icon} <code>#{p['id']}</code> — {p['amount']:,} ت — 👤 {html.escape(str(buyer))} "
            f"(<code>{p['user_id']}</code>) — {_fmt_dt(p.get('created_at'))}"
        )
    label = _PAY_STATUS_FA.get(flt, "همه")
    text = texts.ADMIN_PAYS_TITLE.format(
        filter_label=label,
        page=page + 1,
        pages=pages,
        total=total,
        rows="\n".join(rows) or "(پرداختی نیست)",
    )
    await _edit_or_answer(cb, text, keyboards.admin_payments_keyboard(pays, flt, page, pages))


@router.callback_query(F.data.startswith("adm:pays:"), AdminFilter())
async def cb_admin_pays(cb: CallbackQuery) -> None:
    await cb.answer()
    parts = cb.data.split(":")  # adm:pays:<flt>:<page>
    flt = parts[2] if len(parts) > 2 else "pending"
    page = _int_maybe(parts[3]) if len(parts) > 3 else 0
    await _render_payments(cb, flt, page or 0)


@router.callback_query(F.data.startswith("adm:pay:ok:"), AdminFilter())
async def cb_pay_approve(cb: CallbackQuery) -> None:
    payment_id = _int_maybe(cb.data.split(":")[3])
    if not payment_id:
        await cb.answer()
        return
    payment = await repo.get_payment_with_buyer(payment_id)
    if not payment:
        await cb.answer(texts.ADMIN_PAY_NOT_FOUND, show_alert=True)
        return
    if payment["status"] != "pending":
        await cb.answer(texts.ADMIN_PAY_ALREADY, show_alert=True)
        return
    await repo.decide_payment(payment_id, "approved")
    await repo.grant_pro(payment["user_id"], config.PRO_DURATION_DAYS)
    child_handlers.invalidate_owner_cache(payment["user_id"])
    await manager.notify_user(
        payment["user_id"],
        texts.PAYMENT_APPROVED_USER.format(
            days=config.PRO_DURATION_DAYS, payment_id=payment_id
        ),
    )
    await cb.answer("✅ تایید شد و پرو فعال شد")
    await _render_payments(cb, "pending", 0)


@router.callback_query(F.data.startswith("adm:pay:no:"), AdminFilter())
async def cb_pay_reject(cb: CallbackQuery) -> None:
    payment_id = _int_maybe(cb.data.split(":")[3])
    if not payment_id:
        await cb.answer()
        return
    payment = await repo.get_payment_with_buyer(payment_id)
    if not payment:
        await cb.answer(texts.ADMIN_PAY_NOT_FOUND, show_alert=True)
        return
    if payment["status"] != "pending":
        await cb.answer(texts.ADMIN_PAY_ALREADY, show_alert=True)
        return
    await repo.decide_payment(payment_id, "rejected")
    await manager.notify_user(
        payment["user_id"],
        texts.PAYMENT_REJECTED_USER.format(payment_id=payment_id),
    )
    await cb.answer("❌ رد شد")
    await _render_payments(cb, "pending", 0)


@router.callback_query(F.data.startswith("adm:pay:"), AdminFilter())
async def cb_admin_pay_detail(cb: CallbackQuery) -> None:
    await cb.answer()
    payment_id = _int_maybe(cb.data.split(":")[2])
    payment = await repo.get_payment_with_buyer(payment_id) if payment_id else None
    if not payment:
        await cb.answer(texts.ADMIN_PAY_NOT_FOUND, show_alert=True)
        return
    buyer = payment.get("buyer_username") or payment.get("buyer_name") or payment["user_id"]
    receipt = html.escape(payment.get("receipt_text") or "")
    receipt_line = f"\n🔢 شماره پیگیری: <code>{receipt}</code>" if receipt else ""
    photo_line = "\n📸 رسید عکس دار (در چنل بررسی ارسال شده)" if payment.get("receipt_file_id") else ""
    text = (
        f"💳 <b>پرداخت #{payment['id']}</b>\n\n"
        f"👤 خریدار: {html.escape(str(buyer))} (<code>{payment['user_id']}</code>)\n"
        f"💰 مبلغ: <b>{payment['amount']:,} تومان</b>\n"
        f"وضعیت: {_PAY_STATUS_ICON.get(payment['status'], '❔')} "
        f"{_PAY_STATUS_FA.get(payment['status'], payment['status'])}\n"
        f"📅 ثبت: {_fmt_dt(payment.get('created_at'))}\n"
        f"⚖️ تصمیم: {_fmt_dt(payment.get('decided_at'))}"
        f"{receipt_line}{photo_line}"
    )
    await _edit_or_answer(cb, text, keyboards.admin_payment_detail_keyboard(payment))


# ------------------------------------------------------------------ broadcast
@router.callback_query(F.data == "adm:bcast", AdminFilter())
async def cb_bcast_ask(cb: CallbackQuery) -> None:
    store.set(cb.from_user.id, Dialog(action="admin:bcast"))
    await cb.answer()
    if cb.message:
        await cb.message.edit_text(texts.ADMIN_BROADCAST_ASK)


@router.message(Dialog.action_filter("admin:bcast"), AdminFilter())
async def msg_bcast_text(message: Message) -> None:
    d = store.get(message.from_user.id)
    if not d:
        await message.answer(texts.DIALOG_EXPIRED)
        return
    text = (message.text or "").strip()
    if not text:
        await message.answer("⚠️ متن خالی قابل ارسال نیست!")
        return
    if len(text) > 4000:
        await message.answer("⚠️ متن خیلی طولانیه! حداکثر ۴۰۰۰ کاراکتر.")
        return
    d.text = text
    store.set(message.from_user.id, d)  # refresh TTL
    ids = await repo.list_broadcast_ids()
    await message.answer(
        texts.ADMIN_BROADCAST_CONFIRM.format(count=len(ids), text=html.escape(text)),
        reply_markup=keyboards.admin_broadcast_confirm_keyboard(),
    )


@router.callback_query(F.data == "adm:bcast:go", AdminFilter())
async def cb_bcast_go(cb: CallbackQuery) -> None:
    d = store.pop(cb.from_user.id)
    if not d or not d.text:
        await cb.answer("⏳ متنی ذخیره نشده؛ دوباره «📣 پیام همگانی» رو بزن.", show_alert=True)
        return
    await cb.answer("📨 در حال ارسال...")

    ids = await repo.list_broadcast_ids()
    text = d.text
    bot = cb.bot
    ok = fail = 0
    status_msg = None
    try:
        status_msg = await bot.send_message(cb.from_user.id, "📨 ارسال شروع شد...")
    except Exception:
        status_msg = None

    for i, uid in enumerate(ids, start=1):
        try:
            await bot.send_message(uid, text, disable_web_page_preview=True)
            ok += 1
        except Exception:
            fail += 1
        if i % 100 == 0 and status_msg is not None:
            try:
                await status_msg.edit_text(f"📨 در حال ارسال... {i}/{len(ids)}")
            except Exception:
                pass
        await asyncio.sleep(_BROADCAST_INTERVAL)

    result = texts.ADMIN_BROADCAST_DONE.format(ok=ok, fail=fail)
    if status_msg is not None:
        try:
            await status_msg.edit_text(result)
        except Exception:
            await bot.send_message(cb.from_user.id, result)
    else:
        await bot.send_message(cb.from_user.id, result)
    log.info("Admin broadcast: %d ok / %d failed", ok, fail)


# ------------------------------------------------------------------ search
@router.callback_query(F.data == "adm:find", AdminFilter())
async def cb_find_ask(cb: CallbackQuery) -> None:
    store.set(cb.from_user.id, Dialog(action="admin:find"))
    await cb.answer()
    if cb.message:
        await cb.message.edit_text(texts.ADMIN_FIND_ASK)


@router.message(Dialog.action_filter("admin:find"), AdminFilter())
async def msg_find(message: Message) -> None:
    if not store.get(message.from_user.id):
        await message.answer(texts.DIALOG_EXPIRED)
        return
    store.pop(message.from_user.id)
    user = await repo.find_user((message.text or "").strip())
    if not user:
        await message.answer(
            texts.ADMIN_USER_NOT_FOUND, reply_markup=keyboards.admin_back_to_panel()
        )
        return
    # reuse the detail renderer via a light fake callback is overkill —
    # render a standalone message
    bots = await repo.list_user_bots(user["user_id"])
    pays = await repo.user_payments(user["user_id"])
    usage = await repo.user_usage_month(user["user_id"])
    referrals = await repo.count_referrals(user["user_id"])
    if repo.is_pro_row(user):
        plan = texts.PLAN_PRO.format(date=_fmt_date(user["pro_until"]))
    else:
        plan = "🆓 رایگان"
    uname = f" — @{user['username']}" if user.get("username") else ""
    pays_ok = sum(1 for p in pays if p["status"] == "approved")
    bots_line = ""
    if bots:
        listed = "، ".join(
            f"@{b['username'] or b['id']}" + ("" if b["active"] else " (⛔)") for b in bots[:5]
        )
        bots_line = "\n🤖 ربات‌های کاربر: " + listed
    await message.answer(
        texts.ADMIN_USER_DETAIL.format(
            name=html.escape(user.get("first_name") or "—"),
            username=uname,
            user_id=user["user_id"],
            plan=plan,
            banned="🚫 بله" if user.get("banned") else "خیر",
            bots=len(bots),
            usage=usage,
            pays_total=len(pays),
            pays_ok=pays_ok,
            pays_pending=sum(1 for p in pays if p["status"] == "pending"),
            referrals=referrals,
            created=_fmt_dt(user.get("created_at")),
            bots_line=bots_line,
        ),
        reply_markup=keyboards.admin_user_detail_keyboard(user),
    )


# ------------------------------------------------------------------ grant dialog
@router.message(Dialog.action_filter("admin:grant_pro"), AdminFilter())
async def msg_grant_days(message: Message) -> None:
    d = store.get(message.from_user.id)
    if not d or not d.target_user_id:
        await message.answer(texts.DIALOG_EXPIRED)
        return
    days = _int_maybe(message.text or "")
    if not days or not (1 <= days <= 3650):
        await message.answer("⚠️ لطفاً یک عدد بین ۱ تا ۳۶۵۰ بفرست (مثلاً 30).")
        return
    user = await repo.get_user(d.target_user_id)
    if not user:
        store.pop(message.from_user.id)
        await message.answer(texts.ADMIN_USER_NOT_FOUND)
        return
    await repo.grant_pro(d.target_user_id, days)
    child_handlers.invalidate_owner_cache(d.target_user_id)
    row = await repo.get_user(d.target_user_id)
    until = _fmt_date((row or {}).get("pro_until"))
    await manager.notify_user(
        d.target_user_id,
        f"🎉 <b>اشتراک 💎 پرو از طرف مدیریت فعال شد!</b>\n\n"
        f"مدت: <b>{days} روز</b>\nاز همه امکانات پرو لذت ببر 🚀",
    )
    store.pop(message.from_user.id)
    await message.answer(
        texts.ADMIN_GRANT_DONE.format(
            days=days, name=html.escape(user.get("first_name") or "—"), until=until
        )
    )
