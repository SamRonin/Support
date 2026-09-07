"""Mother bot router: /start, main menu, help."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from .. import config, keyboards, repo, texts
from ..states import store

router = Router(name="mother:start")


def _plan_status(user) -> str:
    if repo.is_pro_row(user):
        until = user["pro_until"].strftime("%Y-%m-%d") if user["pro_until"] else "نامحدود"
        return texts.PLAN_PRO.format(date=until)
    return texts.PLAN_FREE


async def _send_menu(message: Message, user_id: int) -> None:
    user = await repo.get_user(user_id)
    bots = await repo.list_user_bots(user_id)
    is_pro = repo.is_pro_row(user)
    max_bots = config.PRO_MAX_BOTS if is_pro else config.FREE_MAX_BOTS
    can_create = len(bots) < max_bots
    await message.answer(
        texts.MAIN_MENU.format(
            plan_status=_plan_status(user),
            bot_count=len(bots),
            max_bots=max_bots,
        ),
        reply_markup=keyboards.main_menu(
            has_bots=bool(bots), can_create=can_create,
            is_admin=config.is_admin(user_id),
        ),
    )


@router.message(CommandStart(deep_link=True))
@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandStart | None = None) -> None:
    user = message.from_user
    if not user:
        return

    # referral deep link: ?start=ref<USER_ID>
    if command and command.args:
        arg = command.args.strip()
        if arg.startswith("ref") and arg[3:].isdigit():
            referrer_id = int(arg[3:])
            if referrer_id != user.id:
                await _register_referral(referrer_id, user.id)

    await message.answer(
        texts.WELCOME.format(name=user.first_name or "دوست عزیز"),
        disable_web_page_preview=True,
    )
    await _send_menu(message, user.id)


async def _register_referral(referrer_id: int, invited_id: int) -> None:
    from ..mother import referral

    is_new = await repo.register_referral(referrer_id, invited_id)
    if not is_new:
        return

    await referral.check_and_reward(referrer_id)

    count = await repo.count_referrals(referrer_id)
    need = config.REFERRAL_INVITES
    remaining = (need - (count % need)) % need or need

    try:
        from ..child import manager

        await manager.notify_user(
            referrer_id,
            texts.REFERRAL_JOINED.format(
                count=count, days=config.REFERRAL_REWARD_DAYS, remaining=remaining
            ),
        )
    except Exception:
        pass  # referrer may have blocked the bot


@router.callback_query(F.data == "menu:main")
async def cb_menu(cb: CallbackQuery) -> None:
    store.pop(cb.from_user.id)
    if not cb.message:
        return
    user = await repo.get_user(cb.from_user.id)
    bots = await repo.list_user_bots(cb.from_user.id)
    is_pro = repo.is_pro_row(user)
    max_bots = config.PRO_MAX_BOTS if is_pro else config.FREE_MAX_BOTS
    can_create = len(bots) < max_bots
    await cb.message.edit_text(
        texts.MAIN_MENU.format(
            plan_status=_plan_status(user),
            bot_count=len(bots),
            max_bots=max_bots,
        ),
        reply_markup=keyboards.main_menu(
            has_bots=bool(bots), can_create=can_create,
            is_admin=config.is_admin(cb.from_user.id),
        ),
    )


@router.callback_query(F.data == "bots:list")
async def cb_bots_list(cb: CallbackQuery) -> None:
    if not cb.message:
        return
    bots = await repo.list_user_bots(cb.from_user.id)
    user = await repo.get_user(cb.from_user.id)
    is_pro = repo.is_pro_row(user)
    max_bots = config.PRO_MAX_BOTS if is_pro else config.FREE_MAX_BOTS
    if not bots:
        await cb.message.edit_text(
            texts.BOT_LIST_EMPTY,
            reply_markup=keyboards.main_menu(has_bots=False, can_create=len(bots) < max_bots),
        )
        return
    await cb.message.edit_text(
        texts.SELECT_BOT,
        reply_markup=keyboards.bots_list_keyboard(bots, can_create=len(bots) < max_bots),
    )


@router.callback_query(F.data == "help:menu")
async def cb_help(cb: CallbackQuery) -> None:
    if not cb.message:
        return
    await cb.message.edit_text(
        "ℹ️ <b>راهنما</b>\n\n"
        "🛠 <b>ساخت ربات:</b> روی «🛠 ساخت ربات جدید» بزن، بعد روی «🛠 ساخت ربات» بزن. "
        "تلگرام خودش <b>فرم رسمی ساخت ربات</b> رو باز می‌کنه؛ اسم و یوزرنیم رو وارد کن و "
        "«Create» رو بزن. ربات خودکار ساخته و فعال می‌شه — دیگه نیازی به توکن یا BotFather نیست!\n\n"
        "🧠 <b>آموزش هوش مصنوعی:</b> توی تنظیمات ربات، کسب‌وکارت رو کامل شرح می‌دی تا "
        "هوش مصنوعی جای ادمین به مشتری‌ها جواب بده.\n\n"
        "🌐 <b>زبان پاسخ AI:</b> هوش مصنوعی همیشه به همان زبانی جواب می‌ده که مشتری "
        "سوالش رو پرسیده؛ اگر اشتباهاً به زبان دیگری جواب داد، خودکار به زبان مشتری ترجمه می‌شه.\n\n"
        "📢 <b>چنل:</b> چنلت رو وصل می‌کنی تا محتواش رو یاد بگیره.\n\n"
        "🔌 <b>Chat Automation:</b> پیام‌های اکانت بیزینست رو خودکار جواب می‌ده.\n\n"
        "💎 <b>نسخه پرو:</b> حافظه مکالمه، مدل‌های قوی‌تر، ربات و چنل بیشتر و آمار کامل.\n\n"
        "🎁 <b>دعوت دوستان:</b> با هر ۳ نفر دعوت موفق، ۱۰ روز پرو رایگان بگیر!\n\n"
        "🆘 <b>پشتیبانی:</b> اگر سوالی داشتی یا مشکلی برات پیش اومد، از دکمه «🆘 پشتیبانی» "
        "مستقیم به آدمین پیام بده.",
        reply_markup=keyboards.back_to_menu(),
    )


@router.message(Command("cancel"))
async def cmd_cancel(message: Message) -> None:
    store.pop(message.from_user.id)
    await message.answer(texts.CANCELLED)
    await _send_menu(message, message.from_user.id)


@router.message(Command("menu"))
async def cmd_menu(message: Message) -> None:
    store.pop(message.from_user.id)
    await _send_menu(message, message.from_user.id)
