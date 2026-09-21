from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import FORCE_JOIN_1, FORCE_JOIN_2
from services.user_service import ensure_user
from keyboards.main import home_kb
from utils.premium_emoji import tag, premium_text
from utils.buttons import btn
from locales.i18n import get_lang, T
from html import escape
from aiogram.types import MessageEntity
router = Router()


async def joined(bot, user_id):
    for ch in [FORCE_JOIN_1, FORCE_JOIN_2]:
        if not ch:
            continue
        try:
            member = await bot.get_chat_member(ch, user_id)
            if member.status in ("left", "kicked"):
                return False
        except Exception:
            return False
    return True


from aiogram.types import Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ParseMode


async def home(message, db):
    lang = await get_lang(db, message.from_user.id)
    maintenance = await db.settings.find_one({'_id':'maintenance'}) or {}
    from config import ADMIN_IDS
    if maintenance.get('enabled') and message.from_user.id not in ADMIN_IDS:
        await message.answer('🛠️ <b>Maintenance Mode</b>\n\nThe store is temporarily unavailable. Please try again later.', parse_mode='HTML')
        return

    text = (
        "🐈‍⬛ Welcome to VESP STORE\n"
        "<blockquote>"
        "🎆 Premium digital products at the cheapest prices\n"
        "⚡️ Instant delivery\n"
        "🔒 Secure payments\n"
        "💬 24/7 Support"
        "</blockquote>\n\n"
        "Choose an option below:"
    )

    emoji_map = {
        "🐈‍⬛": "6129399728506412489",
        "🎆": "6129870783339567154",
        "⚡️": "5400280896311944960",
        "🔒": "5330066942755615469",
        "💬": "5040036030414062506",
    }

    # Remove the HTML blockquote from the text and use
    # a Telegram blockquote entity instead.
    plain_text = (
        "🐈‍⬛ Welcome to VESP STORE\n"
        "🎆 Premium digital products at the cheapest prices\n"
        "⚡️ Instant delivery\n"
        "🔒 Secure payments\n"
        "💬 24/7 Support\n\n"
        "Choose an option below:"
    )

    text, entities = premium_text(
        plain_text,
        emoji_map,
    )

    # Add the blockquote entity around the four feature lines.
    block_start = (
        len("🐈‍⬛ Welcome to VESP STORE\n".encode("utf-16-le")) // 2
    )

    block_content = (
        "🎆 Premium digital products at the cheapest prices\n"
         "⚡️ Instant delivery\n"
        "🔒 Secure payments\n"
        "💬 24/7 Support"
    )

    block_length = (
        len(block_content.encode("utf-16-le")) // 2
)

    from aiogram.types import MessageEntity

    entities.append(
        MessageEntity(
            type="blockquote",
            offset=block_start,
            length=block_length,
        )
    )

    await message.answer(
        text,
        entities=entities,
        reply_markup=home_kb(lang),
    )


async def finalize_referral(bot, db, user_id):
    """
    Credit a referral only after the referred user has successfully
    passed the force-join check. The referred user is marked so the
    reward can never be paid twice.
    """
    user = await db.users.find_one({"telegram_id": user_id})
    if not user:
        return

    referrer_id = user.get("referred_by")
    if not referrer_id or user.get("referral_rewarded"):
        return
    if int(referrer_id) == int(user_id):
        return

    settings = await db.settings.find_one({"_id": "referrals"}) or {}
    if not settings.get("enabled", True):
        return

    try:
        reward = float(settings.get("reward", 1.0))
    except Exception:
        reward = 1.0

    if reward < 0:
        reward = 0.0

    referrer = await db.users.find_one({"telegram_id": int(referrer_id)})
    if not referrer:
        return

    # Mark first so repeated /start or check_join cannot pay twice.
    marked = await db.users.update_one(
        {"telegram_id": user_id, "referral_rewarded": {"$ne": True}},
        {"$set": {"referral_rewarded": True}},
    )
    if marked.modified_count != 1:
        return

    await db.users.update_one(
        {"telegram_id": int(referrer_id)},
        {
            "$inc": {
                "balance": reward,
                "referrals": 1,
                "referral_earnings": reward,
            }
        },
    )
    await db.balance_ledger.insert_one({
        'user_id': int(referrer_id), 'admin_id': 0, 'delta': reward,
        'action': 'referral_reward', 'reason': f'Referral reward for user {user_id}',
        'balance_after': float((await db.users.find_one({'telegram_id': int(referrer_id)})).get('balance', 0)),
        'created_at': __import__('datetime').datetime.now(__import__('datetime').timezone.utc),
    })

    try:
        await bot.send_message(
            int(referrer_id),
            f"{tag('refer')} <b>Referral Reward</b>\n\n"
            f"A referred user completed verification.\n"
            f"Reward: <b>₹{reward:.2f}</b>",
            parse_mode="HTML",
        )
    except Exception:
        pass


async def show_join_required(m, x):
    kb = InlineKeyboardBuilder()
    for i, ch in enumerate([FORCE_JOIN_1, FORCE_JOIN_2], 1):
        if ch:
            kb.row(btn(f"Channel {i}", url=f"https://t.me/{ch.lstrip('@')}", emoji_key="forcejoin"))
    kb.row(btn(x["joined"], callback_data="check_join", emoji_key="confirm", style="success"))
    kb.adjust(1)
    return await m.answer(
        f"🔒 <b>{x['join_required']}</b>\n\n{x['join_text']}",
        parse_mode="HTML",
        reply_markup=kb.as_markup(),
    )


@router.message(CommandStart())
async def start(m, bot, db):
    user = await ensure_user(db, m.from_user)

    # Save the referral relationship first. No money is paid here.
    if (
        m.text
        and " " in m.text
        and m.text.split(" ", 1)[1].startswith("ref_")
        and not user.get("referred_by")
    ):
        try:
            referrer_id = int(m.text.split(" ", 1)[1][4:])
            if (
                referrer_id != m.from_user.id
                and await db.users.find_one({"telegram_id": referrer_id})
            ):
                await db.users.update_one(
                    {"telegram_id": m.from_user.id},
                    {"$set": {"referred_by": referrer_id}},
                )
        except Exception:
            pass

    user = await ensure_user(db, m.from_user)
    lang = await get_lang(db, m.from_user.id)
    x = T[lang]

    if not await joined(bot, m.from_user.id):
        return await show_join_required(m, x)

    await finalize_referral(bot, db, m.from_user.id)
    await home(m, db)


@router.callback_query(F.data == "check_join")
async def check(cq, bot, db):
    lang = await get_lang(db, cq.from_user.id)
    x = T[lang]

    if not await joined(bot, cq.from_user.id):
        return await cq.answer(
            x["join_both"],
            show_alert=True
        )

    await finalize_referral(bot, db, cq.from_user.id)
    await ensure_user(db, cq.from_user)

    await cq.answer()

    # Build the same premium home message used by /start
    plain_text = (
        "🐈‍⬛ Welcome to VESP STORE\n"
        "🎆 Premium digital products at the cheapest prices\n"
        "⚡️ Instant delivery\n"
        "🔒 Secure payments\n"
        "💬 24/7 Support\n\n"
        "Choose an option below:"
    )

    emoji_map = {
        "🐈‍⬛": "6129399728506412489",
        "🎆": "6129870783339567154",
        "⚡️": "5400280896311944960",
        "🔒": "5330066942755615469",
        "💬": "5040036030414062506",
    }

    text, entities = premium_text(
        plain_text,
        emoji_map,
    )

    block_start = (
        len("🐈‍⬛ Welcome to VESP STORE\n".encode("utf-16-le")) // 2
    )

    block_content = (
        "🎆 Premium digital products at the cheapest prices\n"
        "⚡️ Instant delivery\n"
        "🔒 Secure payments\n"
        "💬 24/7 Support "
    )

    block_length = (
        len(block_content.encode("utf-16-le")) // 2
    )

    entities.append(
        MessageEntity(
            type="blockquote",
            offset=block_start,
            length=block_length,
        )
    )

    await cq.message.edit_text(
        text,
        entities=entities,
        reply_markup=home_kb(lang),
    )