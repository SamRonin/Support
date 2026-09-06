"""Pro purchase flow: card info -> receipt -> private channel -> approve/reject."""

from __future__ import annotations

import html

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, Message

from .. import config, keyboards, repo, texts
from ..child import handlers as child_handlers
from ..states import Dialog, store

router = Router(name="mother:purchase")


@router.callback_query(F.data == "buy:menu")
async def cb_buy_menu(cb: CallbackQuery) -> None:
    if not cb.message:
        return
    await cb.message.edit_text(
        texts.PURCHASE_MENU.format(
            price=config.PRO_PRICE_TOMAN, duration=config.PRO_DURATION_DAYS
        ),
        reply_markup=keyboards.purchase_keyboard(),
    )


@router.callback_query(F.data == "buy:start")
async def cb_buy_start(cb: CallbackQuery) -> None:
    if not cb.message:
        return
    payment_id = await repo.create_payment(cb.from_user.id, config.PRO_PRICE_TOMAN)
    store.set(
        cb.from_user.id,
        Dialog(action="buy:receipt", payment_id=payment_id),
    )
    await cb.message.edit_text(
        texts.PURCHASE_CARD_INFO.format(
            card=config.CARD_NUMBER,
            holder=config.CARD_HOLDER,
            amount=config.PRO_PRICE_TOMAN,
            payment_id=payment_id,
        )
    )


@router.message(Dialog.action_filter("buy:receipt"))
async def msg_receipt(message: Message) -> None:
    d = store.get(message.from_user.id)
    if not d or not d.payment_id:
        await message.answer(texts.DIALOG_EXPIRED)
        return

    # a photo receipt usually carries the tracking number as its caption
    receipt_text = (message.caption or message.text or "").strip()
    receipt_file_id = None
    if message.photo:
        receipt_file_id = message.photo[-1].file_id
    elif not receipt_text:
        await message.answer("⚠️ لطفاً عکس رسید یا شماره پیگیری رو بفرست.")
        return  # dialog stays alive for retry


    store.pop(message.from_user.id)
    await repo.set_payment_receipt(d.payment_id, receipt_text or None, receipt_file_id)

    # forward to the private channel for admin review
    if not config.PRIVATE_CHANNEL_ID:
        await message.answer(
            "✅ رسیدت ثبت شد! ولی چنل بررسی تنظیم نشده؛ به ادمین اطلاع بده."
        )
        return

    user = await repo.get_user(message.from_user.id)
    uname = f"@{user['username']}" if user and user["username"] else "بدون یوزرنیم"
    full_name = html.escape(user["first_name"] or "") if user else ""
    caption = (
        f"🧾 <b>درخواست خرید نسخه پرو</b>\n\n"
        f"🆔 شناسه خرید: <code>#{d.payment_id}</code>\n"
        f"👤 کاربر: {full_name} ({html.escape(uname)})\n"
        f"🆔 آیدی عددی: <code>{message.from_user.id}</code>\n"
        f"💰 مبلغ: <b>{config.PRO_PRICE_TOMAN:,} تومان</b>\n\n"
        + (f"🔢 شماره پیگیری: <code>{html.escape(receipt_text)}</code>" if receipt_text else "📸 رسید به‌صورت عکس")
    )

    try:
        bot: Bot = message.bot
        sent = None
        if receipt_file_id:
            sent = await bot.send_photo(
                config.PRIVATE_CHANNEL_ID, receipt_file_id, caption=caption,
                reply_markup=keyboards.admin_decision_keyboard(d.payment_id),
            )
        else:
            sent = await bot.send_message(
                config.PRIVATE_CHANNEL_ID, caption,
                reply_markup=keyboards.admin_decision_keyboard(d.payment_id),
            )
        await message.answer(
            texts.RECEIPT_RECEIVED.format(payment_id=d.payment_id)
        )
    except Exception:
        await message.answer(
            "⚠️ ارسال رسید به چنل بررسی ناموفق بود! لطفاً بعداً تلاش کن یا به ادمین پیام بده."
        )


@router.callback_query(F.data.startswith("pay:approve:"))
async def cb_approve(cb: CallbackQuery) -> None:
    if not config.is_admin(cb.from_user.id):
        await cb.answer("⛔ فقط ادمین می‌تونه تصمیم بگیره!", show_alert=True)
        return
    payment_id = int(cb.data.split(":")[2])
    payment = await repo.get_payment(payment_id)
    if not payment or payment["status"] != "pending":
        await cb.answer("⚠️ این قبلاً بررسی شده!", show_alert=True)
        return

    await repo.decide_payment(payment_id, "approved")
    await repo.grant_pro(payment["user_id"], config.PRO_DURATION_DAYS)
    child_handlers.invalidate_owner_cache(payment["user_id"])

    try:
        await cb.message.edit_reply_markup(
            reply_markup=None  # remove decision buttons
        )
    except Exception:
        pass
    await cb.answer(texts.ADMIN_DONE)

    from ..child import manager

    await manager.notify_user(
        payment["user_id"],
        texts.PAYMENT_APPROVED_USER.format(
            days=config.PRO_DURATION_DAYS, payment_id=payment_id
        ),
    )
    # edit caption/text to show decision
    try:
        if cb.message.caption is not None:
            await cb.message.edit_caption(
                cb.message.caption + "\n\n✅ <b>تایید شد</b>"
            )
        else:
            await cb.message.edit_text((cb.message.text or "") + "\n\n✅ <b>تایید شد</b>")
    except Exception:
        pass


@router.callback_query(F.data.startswith("pay:reject:"))
async def cb_reject(cb: CallbackQuery) -> None:
    if not config.is_admin(cb.from_user.id):
        await cb.answer("⛔ فقط ادمین می‌تونه تصمیم بگیره!", show_alert=True)
        return
    payment_id = int(cb.data.split(":")[2])
    payment = await repo.get_payment(payment_id)
    if not payment or payment["status"] != "pending":
        await cb.answer("⚠️ این قبلاً بررسی شده!", show_alert=True)
        return

    await repo.decide_payment(payment_id, "rejected")
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await cb.answer("❌ رد شد")

    from ..child import manager

    await manager.notify_user(
        payment["user_id"], texts.PAYMENT_REJECTED_USER.format(payment_id=payment_id)
    )
    try:
        if cb.message.caption is not None:
            await cb.message.edit_caption(cb.message.caption + "\n\n❌ <b>رد شد</b>")
        else:
            await cb.message.edit_text((cb.message.text or "") + "\n\n❌ <b>رد شد</b>")
    except Exception:
        pass
