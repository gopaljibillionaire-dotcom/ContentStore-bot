from aiogram import Router, F
from keyboards.main import home_kb
from services.user_service import get_user
from utils.text import price
from config import SUPPORT_USERNAME, REVIEWS_URL, SELL_SUPPORT_USERNAME, BOT_USERNAME
from locales.i18n import t, language_keyboard, LANGUAGES, get_lang, T
from utils.premium_emoji import tag, premium_text
from aiogram.types import MessageEntity
from utils.buttons import btn
from aiogram.utils.keyboard import InlineKeyboardBuilder

router = Router()

def back_home_kb(lang):
    x = T[lang]
    b = InlineKeyboardBuilder()
    b.row(btn(x['back'], callback_data='home', emoji_key='back', style='danger'))
    return b.as_markup()

@router.callback_query(F.data == 'home')
async def home(cq, db):
    lang = await get_lang(db, cq.from_user.id)

    await cq.answer()

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
        "💬 24/7 Support"
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

    try:
        await cq.message.edit_text(
        text,
        entities=entities,
        reply_markup=home_kb(lang)
    )
    except Exception:
        try:
            await cq.message.delete()
        except Exception:
           pass

        await cq.message.answer(
        text,
        entities=entities,
        reply_markup=home_kb(lang)
    )
@router.callback_query(F.data == 'wallet')
async def wallet(cq, db):
    u = await get_user(db, cq.from_user.id); lang = await get_lang(db, cq.from_user.id); x = T[lang]
    b = InlineKeyboardBuilder()
    b.row(btn(x['add_money'], callback_data='recharge', emoji_key='recharge', style='success'))
    b.row(btn(x['back'], callback_data='home', emoji_key='back', style='danger'))
    await cq.answer()
    await cq.message.edit_text(f'{tag("wallet")} <b>{x["wallet"]}</b>\n\n{tag("money")} {x["balance"]}: <b>{price(u.get("balance", 0))}</b>', parse_mode='HTML', reply_markup=b.as_markup())

@router.callback_query(F.data == 'profile')
async def profile(cq, db):
    u = await get_user(db, cq.from_user.id); lang = await get_lang(db, cq.from_user.id); x = T[lang]
    text = (f'{tag("profile")} <b>{x["profile"]}</b>\n\n'
            f'👤 {x["profile_name"]}: {u.get("full_name", "")}\n'
            f'🆔 ID: <code>{u["telegram_id"]}</code>\n'
            f'🔗 {x["username"]}: @{u.get("username") or "N/A"}\n'
            f'{tag("money")} {x["balance"]}: {price(u.get("balance", 0))}')
    await cq.answer(); await cq.message.edit_text(text, parse_mode='HTML', reply_markup=back_home_kb(lang))

@router.callback_query(F.data == 'reviews')
async def reviews(cq, db):
    lang = await get_lang(db, cq.from_user.id); x = T[lang]
    b = InlineKeyboardBuilder(); b.row(btn(x['reviews_open'], url=REVIEWS_URL, emoji_key='reviews'))
    b.row(btn(x['back'], callback_data='home', emoji_key='back', style='danger'))
    await cq.answer(); await cq.message.edit_text(f'{tag("reviews")} <b>{x["reviews"]}</b>\n\n{x["reviews_text"]}', parse_mode='HTML', reply_markup=b.as_markup())

@router.callback_query(F.data == 'support')
async def support(cq, db):
    lang = await get_lang(db, cq.from_user.id); x = T[lang]
    await cq.answer(); await cq.message.edit_text(f'{tag("support")} <b>{x["support"]}</b>\n\n{x["support_text"].format(support=SUPPORT_USERNAME)}', parse_mode='HTML', reply_markup=back_home_kb(lang))

@router.callback_query(F.data == 'sell')
async def sell(cq, db):
    lang = await get_lang(db, cq.from_user.id); x = T[lang]
    await cq.answer(); await cq.message.edit_text(f'{tag("sell")} <b>{x["sell"]}</b>\n\n{x["sell_text"].format(support=SELL_SUPPORT_USERNAME)}', parse_mode='HTML', reply_markup=back_home_kb(lang))

@router.callback_query(F.data == 'refer')
async def refer(cq, db):
    lang = await get_lang(db, cq.from_user.id); x = T[lang]
    link = f'https://t.me/{BOT_USERNAME}?start=ref_{cq.from_user.id}' if BOT_USERNAME else 'Set BOT_USERNAME in .env'
    await cq.answer(); await cq.message.edit_text(f'{tag("refer")} <b>{x["refer"]}</b>\n\n{x["referral_link"]}:\n<code>{link}</code>', parse_mode='HTML', reply_markup=back_home_kb(lang))

@router.callback_query(F.data == 'language')
async def language(cq, db):
    lang = await get_lang(db, cq.from_user.id); x = T[lang]
    b = InlineKeyboardBuilder()
    for row in language_keyboard().inline_keyboard:
        b.row(*row)
    b.row(btn(x['back'], callback_data='home', emoji_key='back', style='danger'))
    await cq.answer(); await cq.message.edit_text(f'{tag("language")} <b>{x["language_title"]}</b>', parse_mode='HTML', reply_markup=b.as_markup())

@router.callback_query(F.data.startswith('lang:'))
async def set_language(cq, db):
    code = cq.data.split(':', 1)[1]
    if code not in LANGUAGES: return await cq.answer('Unknown language', show_alert=True)
    await db.users.update_one({'telegram_id': cq.from_user.id}, {'$set': {'language': code}})
    x = T[code]; await cq.answer(x['language_saved'].format(language=LANGUAGES[code]))
    await cq.message.edit_text(f'{tag("home")} <b>{x["welcome"]}</b>\n\n{x["choose"]}', parse_mode='HTML', reply_markup=home_kb(code))
