from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from . import config, texts


def main_menu(has_bots: bool, can_create: bool, is_admin: bool = False) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if is_admin:
        kb.button(text="🛡 پنل مدیریت", callback_data="adm:menu")
    if has_bots:
        kb.button(text="🤖 ربات‌های من", callback_data="bots:list")
    if can_create:
        kb.button(text="🛠 ساخت ربات جدید", callback_data="bot:create")
    kb.button(text="💎 خرید نسخه پرو", callback_data="buy:menu")
    kb.button(text="🎁 دعوت دوستان", callback_data="ref:menu")
    kb.button(text="ℹ️ راهنما", callback_data="help:menu")
    if is_admin:
        kb.adjust(1, 2, 1, 1, 1)
    else:
        kb.adjust(2, 1, 1, 1)
    return kb.as_markup()


def bots_list_keyboard(bots, can_create: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for b in bots:
        title = b["title"] or b["username"] or f"Bot #{b['id']}"
        uname = b["username"] or b["id"]
        kb.button(text=f"🤖 {title} (@{uname})", callback_data=f"bot:open:{b['id']}")
    if can_create:
        kb.button(text="🛠 ساخت ربات جدید", callback_data="bot:create")
    kb.button(text="🔙 منوی اصلی", callback_data="menu:main")
    kb.adjust(1)
    return kb.as_markup()


def bot_settings_keyboard(bot, biz_connected_hint: bool = False) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📝 اسم", callback_data=f"set:title:{bot['id']}")
    kb.button(text="🖼 عکس پروفایل", callback_data=f"set:photo:{bot['id']}")
    kb.button(text="🪪 بیو", callback_data=f"set:bio:{bot['id']}")
    kb.button(text="ℹ️ توضیحات", callback_data=f"set:desc:{bot['id']}")
    kb.button(text="🖼 عکس توضیحات", callback_data=f"set:descphoto:{bot['id']}")
    kb.button(text="🧠 دانش کسب‌وکار", callback_data=f"set:knowledge:{bot['id']}")
    kb.button(text="📢 چنل‌ها", callback_data=f"set:channels:{bot['id']}")
    kb.button(text="💬 پیام خوش‌آمد 💎", callback_data=f"set:welcome:{bot['id']}")
    kb.button(text="🤖 مدل هوش مصنوعی", callback_data=f"set:model:{bot['id']}")
    kb.button(text="🔌 Chat Automation", callback_data=f"set:business:{bot['id']}")
    kb.button(text="📊 آمار 💎", callback_data=f"set:stats:{bot['id']}")
    kb.button(text="🗑 حذف ربات", callback_data=f"bot:del:{bot['id']}")
    kb.button(text="🔙 بازگشت", callback_data="bots:list")
    kb.adjust(2, 2, 2, 1, 1, 1, 1, 1, 1, 1)
    return kb.as_markup()


def photo_keyboard(bot_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🗑 حذف عکس", callback_data=f"set:photo:del:{bot_id}")
    kb.button(text="🔙 بازگشت", callback_data=f"bot:open:{bot_id}")
    kb.adjust(2)
    return kb.as_markup()


def channels_keyboard(bot, can_add: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    # index-based callbacks: channel names/invite codes can overflow the
    # 64-byte callback_data limit and break the whole keyboard
    for idx, ch in enumerate(bot["channels"] or []):
        label = ch if ch.startswith("+") else f"@{ch}"
        kb.button(text=f"❌ {label}", callback_data=f"ch:del:{bot['id']}:{idx}")
    if can_add:
        kb.button(text="➕ اتصال چنل جدید", callback_data=f"ch:add:{bot['id']}")
    kb.button(text="🔌 راهنمای Chat Automation", callback_data=f"set:business:{bot['id']}")
    kb.button(text="🔙 بازگشت", callback_data=f"bot:open:{bot['id']}")
    kb.adjust(1)
    return kb.as_markup()


def model_keyboard(bot_id: int, models: list[str], current: str | None) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for m in models:
        label = config.SUPPORTED_MODELS.get(m, m)
        if m == current:
            label = f"✅ {label}"
        kb.button(text=label, callback_data=f"model:{bot_id}:{m}")
    kb.button(text="🔙 بازگشت", callback_data=f"bot:open:{bot_id}")
    kb.adjust(1)
    return kb.as_markup()


def purchase_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=f"💳 پرداخت {config.PRO_PRICE_TOMAN:,} تومان", callback_data="buy:start")
    kb.button(text="🔙 منوی اصلی", callback_data="menu:main")
    kb.adjust(1)
    return kb.as_markup()


def admin_decision_keyboard(payment_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ تایید", callback_data=f"pay:approve:{payment_id}")
    kb.button(text="❌ رد", callback_data=f"pay:reject:{payment_id}")
    kb.adjust(2)
    return kb.as_markup()


def delete_confirm_keyboard(bot_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🗑 بله، حذف کن", callback_data=f"bot:del:yes:{bot_id}")
    kb.button(text="❌ انصراف", callback_data=f"bot:open:{bot_id}")
    kb.adjust(2)
    return kb.as_markup()


def referral_keyboard(link: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    url = f"https://t.me/share/url?url={link}&text=این ربات پشتیبانی هوش مصنوعی رو امتحان کن!"
    kb.button(text="📤 اشتراک‌گذاری", url=url)
    kb.button(text="🔁 بروزرسانی", callback_data="ref:menu")
    kb.button(text="🔙 منوی اصلی", callback_data="menu:main")
    kb.adjust(1)
    return kb.as_markup()


def back_to_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔙 منوی اصلی", callback_data="menu:main")
    return kb.as_markup()  # was: `return kb` — sent the Builder object and crashed every caller


def after_create_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="⚙️ تنظیمات ربات", callback_data="bots:list")
    kb.button(text="🏠 منوی اصلی", callback_data="menu:main")
    kb.adjust(1)
    return kb.as_markup()


def back_to_bot(bot_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔙 بازگشت به تنظیمات", callback_data=f"bot:open:{bot_id}")
    return kb.as_markup()


# ------------------------------------------------------------------ admin panel
def admin_main_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📊 بروزرسانی آمار", callback_data="adm:menu")
    kb.button(text="👥 کاربران", callback_data="adm:users:0")
    kb.button(text="🤖 ربات‌ها", callback_data="adm:bots:0")
    kb.button(text="💳 پرداخت‌ها", callback_data="adm:pays:pending:0")
    kb.button(text="📣 پیام همگانی", callback_data="adm:bcast")
    kb.button(text="🔍 جستجوی کاربر", callback_data="adm:find")
    kb.button(text="🔙 منوی اصلی", callback_data="menu:main")
    kb.adjust(1, 2, 2, 1, 1)
    return kb.as_markup()


def _pager(kb: "InlineKeyboardBuilder", base: str, page: int, pages: int) -> None:
    row = []
    if page > 0:
        row.append(InlineKeyboardButton(text="◀️ قبلی", callback_data=f"{base}:{page - 1}"))
    if page + 1 < pages:
        row.append(InlineKeyboardButton(text="بعدی ▶️", callback_data=f"{base}:{page + 1}"))
    if row:
        kb.row(*row)


def admin_users_keyboard(users: list, page: int, pages: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for u in users:
        badges = ("💎 " if repo_is_pro(u) else "") + ("🚫 " if u.get("banned") else "")
        name = (u.get("first_name") or "—")[:25]
        kb.button(
            text=f"👤 {badges}{name}",
            callback_data=f"adm:u:{u['user_id']}",
        )
    _pager(kb, "adm:users", page, pages)
    kb.button(text="🔙 پنل مدیریت", callback_data="adm:menu")
    kb.adjust(1)
    return kb.as_markup()


def admin_user_detail_keyboard(user: dict, has_payments: bool = False) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if repo_is_pro(user):
        kb.button(text="❌ حذف پرو", callback_data=f"adm:u:unpro:{user['user_id']}")
    else:
        kb.button(text="💎 هدیه پرو", callback_data=f"adm:u:grant:{user['user_id']}")
    if user.get("banned"):
        kb.button(text="✅ رفع بن", callback_data=f"adm:u:unban:{user['user_id']}")
    else:
        kb.button(text="🚫 بن کاربر", callback_data=f"adm:u:ban:{user['user_id']}")
    kb.button(text="💳 سابقه خریدها", callback_data=f"adm:u:pays:{user['user_id']}")
    kb.button(text="🔙 کاربران", callback_data="adm:users:0")
    kb.button(text="🛡 پنل مدیریت", callback_data="adm:menu")
    kb.adjust(2, 1, 1, 1)
    return kb.as_markup()


def admin_bots_keyboard(bots: list, page: int, pages: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for b in bots:
        status = "✅" if b.get("active") else "⛔"
        name = (b.get("title") or b.get("username") or f"#{b['id']}")[:25]
        kb.button(
            text=f"{status} {name}",
            callback_data=f"adm:b:{b['id']}",
        )
    _pager(kb, "adm:bots", page, pages)
    kb.button(text="🔙 پنل مدیریت", callback_data="adm:menu")
    kb.adjust(1)
    return kb.as_markup()


def admin_bot_detail_keyboard(bot: dict) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if bot.get("active"):
        kb.button(text="⛔ خاموش کردن", callback_data=f"adm:b:off:{bot['id']}")
    else:
        kb.button(text="✅ روشن کردن", callback_data=f"adm:b:on:{bot['id']}")
    kb.button(text="🗑 حذف ربات", callback_data=f"adm:b:del:{bot['id']}")
    kb.button(text="🔙 ربات‌ها", callback_data="adm:bots:0")
    kb.button(text="🛡 پنل مدیریت", callback_data="adm:menu")
    kb.adjust(1)
    return kb.as_markup()


def admin_bot_delete_keyboard(bot_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🗑 بله، حذف کن", callback_data=f"adm:b:delyes:{bot_id}")
    kb.button(text="❌ انصراف", callback_data=f"adm:b:{bot_id}")
    kb.adjust(2)
    return kb.as_markup()


_PAY_FILTERS = [
    ("⏳ در انتظار", "pending"),
    ("✅ تاییدشده", "approved"),
    ("❌ ردشده", "rejected"),
    ("📋 همه", "all"),
]


def admin_payments_keyboard(
    pays: list, flt: str, page: int, pages: int
) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for p in pays:
        icon = {"pending": "⏳", "approved": "✅", "rejected": "❌"}.get(p["status"], "❔")
        kb.button(
            text=f"{icon} #{p['id']} — {p['amount']:,} ت",
            callback_data=f"adm:pay:{p['id']}",
        )
        if p["status"] == "pending":
            kb.row(
                InlineKeyboardButton(text=f"✅ تایید #{p['id']}", callback_data=f"adm:pay:ok:{p['id']}"),
                InlineKeyboardButton(text=f"❌ رد #{p['id']}", callback_data=f"adm:pay:no:{p['id']}"),
            )
    _pager(kb, f"adm:pays:{flt}", page, pages)
    row = [
        InlineKeyboardButton(text=label, callback_data=f"adm:pays:{value}:0")
        for label, value in _PAY_FILTERS
        if value != flt
    ]
    kb.row(*row)
    kb.button(text="🔙 پنل مدیریت", callback_data="adm:menu")
    return kb.as_markup()


def admin_payment_detail_keyboard(payment: dict) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if payment["status"] == "pending":
        kb.button(text="✅ تایید", callback_data=f"adm:pay:ok:{payment['id']}")
        kb.button(text="❌ رد", callback_data=f"adm:pay:no:{payment['id']}")
        kb.adjust(2)
    kb.button(text="💳 کاربر", callback_data=f"adm:u:{payment['user_id']}")
    kb.button(text="🔙 پرداخت‌ها", callback_data=f"adm:pays:{payment['status']}:0")
    kb.button(text="🛡 پنل مدیریت", callback_data="adm:menu")
    kb.adjust(1)
    return kb.as_markup()


def admin_broadcast_confirm_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ ارسال کن", callback_data="adm:bcast:go")
    kb.button(text="❌ انصراف", callback_data="adm:menu")
    kb.adjust(2)
    return kb.as_markup()


def admin_back_to_panel() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🛡 پنل مدیریت", callback_data="adm:menu")
    return kb.as_markup()


def admin_grant_days_keyboard(user_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="۳۰ روز", callback_data=f"adm:u:grantd:{user_id}:30")
    kb.button(text="۹۰ روز", callback_data=f"adm:u:grantd:{user_id}:90")
    kb.button(text="۳۶۵ روز", callback_data=f"adm:u:grantd:{user_id}:365")
    kb.button(text="❌ انصراف", callback_data=f"adm:u:{user_id}")
    kb.adjust(3, 1)
    return kb.as_markup()


def admin_ban_confirm_keyboard(user_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🚫 بله، بن کن", callback_data=f"adm:u:banyes:{user_id}")
    kb.button(text="❌ انصراف", callback_data=f"adm:u:{user_id}")
    kb.adjust(2)
    return kb.as_markup()


def repo_is_pro(user: dict) -> bool:
    """Tiny local helper (avoids importing repo into keyboards — repo
    imports nothing from keyboards, but keep the import graph one-way)."""
    if not user or not user.get("is_pro"):
        return False
    import datetime as _dt

    until = user.get("pro_until")
    return until is None or until > _dt.datetime.now(_dt.timezone.utc)
