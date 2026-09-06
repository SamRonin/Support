from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from . import config, texts


def main_menu(has_bots: bool, can_create: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if has_bots:
        kb.button(text="🤖 ربات‌های من", callback_data="bots:list")
    if can_create:
        kb.button(text="🛠 ساخت ربات جدید", callback_data="bot:create")
    kb.button(text="💎 خرید نسخه پرو", callback_data="buy:menu")
    kb.button(text="🎁 دعوت دوستان", callback_data="ref:menu")
    kb.button(text="ℹ️ راهنما", callback_data="help:menu")
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
    for ch in bot["channels"]:
        kb.button(text=f"❌ @{ch}", callback_data=f"ch:del:{bot['id']}:{ch}")
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
    return kb.as_markup()


def back_to_bot(bot_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔙 بازگشت به تنظیمات", callback_data=f"bot:open:{bot_id}")
    return kb.as_markup()
