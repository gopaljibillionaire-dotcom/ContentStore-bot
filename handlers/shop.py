from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest
from bson import ObjectId
from html import escape

from services.shop_service import categories, subs, products, product, search_products
from services.purchase_service import purchase, deliver_product
from services.user_service import get_user
from services.logging_service import log_purchase
from keyboards.shop import category_kb, sub_kb, product_kb, product_detail_kb, purchase_success_kb
from keyboards.main import home_kb
from utils.text import product_list, price
from locales.i18n import get_lang, T
from utils.buttons import btn
from utils.premium_emoji import tag
from aiogram.utils.keyboard import InlineKeyboardBuilder

router = Router()


class Qty(StatesGroup):
    search = State()
    custom = State()


async def edit_shop_message(cq: CallbackQuery, text: str, reply_markup=None):
    """Edit either text messages or photo captions without breaking photo sub-category flows."""
    try:
        if cq.message.photo:
            return await cq.message.edit_caption(caption=text, parse_mode='HTML', reply_markup=reply_markup)
        return await cq.message.edit_text(text, parse_mode='HTML', reply_markup=reply_markup)
    except TelegramBadRequest as exc:
        if 'message is not modified' in str(exc).lower():
            return cq.message
        raise


async def edit_prompt(bot, chat_id, message_id, text, reply_markup=None):
    if not message_id:
        return None
    try:
        return await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            parse_mode='HTML',
            reply_markup=reply_markup,
        )
    except Exception:
        try:
            return await bot.edit_message_caption(
                chat_id=chat_id,
                message_id=message_id,
                caption=text,
                parse_mode='HTML',
                reply_markup=reply_markup,
            )
        except Exception:
            return None


@router.callback_query(F.data == 'products')
async def cats(cq, db):
    lang = await get_lang(db, cq.from_user.id)
    x = T[lang]
    xs = await categories(db)
    await cq.answer('Loading categories…')
    text = f'{tag("products")} <b>{x["choose_category"]}</b>\n\n{x["available"]}'
    await edit_shop_message(cq, text, category_kb(xs, lang))


async def _render_subcategory(cq, db, sid, catid, lang):
    x = T[lang]

    # ---------------------------------------------------------
    # LOAD SUB-CATEGORY FIRST
    # ---------------------------------------------------------
    try:
        subdoc = await db.subcategories.find_one({
            "_id": ObjectId(sid)
        })
    except Exception:
        subdoc = None

    if not subdoc:
        await edit_shop_message(
            cq,
            "❌ <b>Sub-category not found.</b>",
            product_kb([], "products", lang),
        )
        return

    # ---------------------------------------------------------
    # NOW LOAD PRODUCTS
    # ---------------------------------------------------------
    ps = await products(db, sub=sid)

    if not subdoc:
        await cq.answer(
            "Sub-category not found.",
            show_alert=True
        )
        return

    # ---------------------------------------------------------
    # SUB-CATEGORY TITLE + PREMIUM EMOJI
    # ---------------------------------------------------------
    sub_name = escape(
        subdoc.get("name") or "Sub-category"
    )

    sub_emoji_id = str(
        subdoc.get("emoji_id") or ""
    ).strip()

    if sub_emoji_id:
        sub_icon = (
            f'<tg-emoji emoji-id="{sub_emoji_id}">🗂️</tg-emoji>'
        )
    else:
        sub_icon = tag("subcategory")

    # ---------------------------------------------------------
    # PRODUCT KEYBOARD
    # ---------------------------------------------------------
    back_callback = (
        f"cat:{catid}"
        if catid
        else "products"
    )

    kb = product_kb(
        ps,
        back_callback,
        lang
    )

    async def _render_subcategory(cq, db, sid, catid, lang):
        x = T[lang]

    # ---------------------------------------------------------
    # LOAD SUB-CATEGORY FIRST
    # ---------------------------------------------------------
    try:
        subdoc = await db.subcategories.find_one({
            "_id": ObjectId(sid)
        })
    except Exception:
        subdoc = None

    if not subdoc:
        await edit_shop_message(
            cq,
            "❌ <b>Sub-category not found.</b>",
            product_kb([], "products", lang),
        )
        return

    # ---------------------------------------------------------
    # NOW LOAD PRODUCTS
    # ---------------------------------------------------------
    ps = await products(db, sub=sid)

    if not subdoc:
        await cq.answer(
            "Sub-category not found.",
            show_alert=True
        )
        return

    # ---------------------------------------------------------
    # SUB-CATEGORY TITLE + PREMIUM EMOJI
    # ---------------------------------------------------------
    sub_name = escape(
        subdoc.get("name") or "Sub-category"
    )

    sub_emoji_id = str(
        subdoc.get("emoji_id") or ""
    ).strip()

    if sub_emoji_id:
        sub_icon = (
            f'<tg-emoji emoji-id="{sub_emoji_id}">🗂️</tg-emoji>'
        )
    else:
        sub_icon = tag("subcategory")

    # ---------------------------------------------------------
    # PAGE TEXT
    # ---------------------------------------------------------
    text = (
        f"{sub_icon} <b>{sub_name}</b>\n\n"
        f"{x.get('choose_product', 'Choose the product to buy below.')}"
    )

    image_id = (
        str(subdoc.get("image_file_id") or "").strip()
    )

    # ---------------------------------------------------------
    # NO IMAGE
    # ---------------------------------------------------------
    if not image_id:
        await edit_shop_message(
            cq,
            text,
            kb
        )
        return

    # ---------------------------------------------------------
    # IMAGE EXISTS
    #
    # IMPORTANT:
    # NEVER DELETE THE OLD MESSAGE BEFORE THE NEW PHOTO
    # HAS SUCCESSFULLY BEEN SENT.
    # ---------------------------------------------------------

    # Already on the same photo?
    if (
        cq.message.photo
        and cq.message.photo[-1].file_id == image_id
    ):
        await edit_shop_message(
            cq,
            text,
            kb
        )
        return

    # First try to send the new photo.
    try:
        new_message = await cq.message.bot.send_photo(
            chat_id=cq.message.chat.id,
            photo=image_id,
            caption=text,
            parse_mode="HTML",
            reply_markup=kb,
        )

    except Exception as exc:
        # DO NOT delete the existing message.
        # If the stored Telegram file_id is invalid/expired,
        # gracefully fall back to a normal text page.
        try:
            await cq.answer(
                "Sub-category image unavailable. Opening products…"
            )
        except Exception:
            pass

        await edit_shop_message(
            cq,
            text,
            kb
        )
        return

    # Only delete the old message AFTER the new photo exists.
    try:
        await cq.message.delete()
    except Exception:
        pass

    return new_message


@router.callback_query(F.data.startswith('cat:'))
async def cat(cq, db):
    lang = await get_lang(db, cq.from_user.id)
    x = T[lang]
    cid = cq.data.split(':', 1)[1]
    xs = await subs(db, cid)
    await cq.answer('Loading…')
    if xs:
        text = f'{tag("category")} <b>{x["choose_subcategory"]}</b>'
        await edit_shop_message(cq, text, sub_kb(xs, cid, lang, back='products'))
    else:
        ps = await products(db, cat=cid)
        text = (
            f'{tag("category")} <b>{x["choose_subcategory"]}</b>\n\n'
            f'{x.get("choose_product", "Choose the product to buy below.")}'
        )
        await edit_shop_message(cq, text, product_kb(ps, 'products', lang))


@router.callback_query(F.data.startswith("sub:"))
async def sub(cq, db):
    try:
        parts = cq.data.split(":")

        if len(parts) < 2:
            return await cq.answer(
                "Invalid sub-category.",
                show_alert=True,
            )

        sid = parts[1]
        catid = parts[2] if len(parts) > 2 else None

        # Get the user's actual language.
        lang = await get_lang(db, cq.from_user.id)

        # Acknowledge callback only once.
        await cq.answer("Loading products…")

        await _render_subcategory(
            cq,
            db,
            sid,
            catid,
            lang,
        )

    except Exception:
        import logging
        logging.exception(
            "SUBCATEGORY ERROR | user=%s | data=%s",
            cq.from_user.id,
            cq.data,
        )

        # Do NOT call cq.answer() again here.
        # The callback has already been answered.

        try:
            lang = await get_lang(db, cq.from_user.id)
        except Exception:
            lang = await get_lang(db, cq.from_user.id)

        try:
            await edit_shop_message(
                cq,
                "❌ <b>Unable to open this sub-category.</b>\n\n"
                "Please try again.",
                sub_kb([], None, lang, back="products"),
            )
        except Exception:
            pass


@router.callback_query(F.data.startswith("prod:"))
async def prod(cq, db):
    lang = await get_lang(db, cq.from_user.id)
    x = T[lang]

    # New compact callback:
    # prod:<product_id>
    parts = cq.data.split(":", 1)

    if len(parts) != 2 or not parts[1]:
        return await cq.answer(
            x["product_unavailable"],
            show_alert=True,
        )

    pid = parts[1]

    # Load the product from MongoDB.
    p = await product(db, pid)

    if not p:
        return await cq.answer(
            x["product_unavailable"],
            show_alert=True,
        )

    # Get navigation IDs directly from the product document.
    sid = str(p.get("subcategory_id") or "")
    catid = str(p.get("category_id") or "")

    stock = (
        x["unlimited"]
        if p.get("stock") is None
        else str(p.get("stock", 0))
    )

    description = (
        p.get("description_html")
        or escape(p.get("description", ""))
    )

    text = (
        f"{tag('buy')} <b>{escape(p['name'])}</b>\n\n"
        f"{description}\n\n"
        f"{tag('money')} {x['price']}: "
        f"<b>{price(p['price'])}</b>\n"
        f"{tag('stock')} {x['stock']}: "
        f"<b>{stock}</b>"
    )

    # Back navigation.
    if sid and catid:
        back = f"sub:{sid}:{catid}"
    elif catid:
        back = f"cat:{catid}"
    else:
        back = "products"

    await cq.answer("Opening product…")

    await edit_shop_message(
        cq,
        text,
        product_detail_kb(
            str(p["_id"]),
            lang,
            back=back,
            sub_id=sid,
        ),
    )


@router.callback_query(F.data.startswith('buy:'))
async def buy(cq, db, bot):
    parts = cq.data.split(':')
    pid = parts[1]
    qty = int(parts[2])
    sid = parts[3] if len(parts) > 3 else ''
    lang = await get_lang(db, cq.from_user.id)
    x = T[lang]
    p = await product(db, pid)
    u = await get_user(db, cq.from_user.id)
    if not p:
        return await cq.answer(x['product_unavailable'], show_alert=True)
    total = float(p['price']) * qty
    if float(u.get('balance', 0)) < total:
        b = InlineKeyboardBuilder()
        b.row(btn(x['recharge'], callback_data='recharge', emoji_key='recharge', style='success'))
        b.row(btn(x['back'], callback_data=f'prod:{pid}:{sid}', emoji_key='back', style='danger'))
        return await edit_shop_message(
            cq,
            f'{tag("money")} <b>{x["insufficient"]}</b>\n\n'
            f'{x["price"]}: {price(total)}\n'
            f'{x["balance"]}: {price(u.get("balance", 0))}\n\n'
            f'{x["add_funds"]}',
            b.as_markup(),
        )
    await cq.answer('Processing purchase…')
    try:
        oid, new = await purchase(db, bot, cq.from_user.id, p, qty)
    except ValueError as e:
        msg = str(e)
        friendly = {
            'SINGLE_STOCK_ONLY': 'This product has single stock. Only 1 purchase is allowed.',
            'OUT_OF_STOCK': 'This product is out of stock.',
            'INSUFFICIENT_BALANCE': 'Insufficient balance.',
            'INVALID_QUANTITY': 'Invalid quantity.',
        }.get(msg, msg.replace('_', ' ').title())
        return await cq.answer(friendly, show_alert=True)
    await log_purchase(
        bot,
        {'product_name': p['name'], 'quantity': qty, 'total': total},
        {**u, 'balance': new['balance']},
        new['balance'],
    )
    delivery_failed = False
    try:
        await deliver_product(bot, cq.from_user.id, p)
    except Exception:
        await bot.send_message(cq.from_user.id, '⚠️ Payment succeeded, but delivery failed. Please contact support.')
    success_text = (
    f'{tag("success")} <b>{x["purchase_ok"]}</b>\n\n'
    f'{tag("stock")} {escape(p["name"])}\n'
    f'{tag("quantity")} {x["quantity"]}: <b>{qty}</b>\n'
    f'{tag("amount")} {x["paid"]}: <b>{price(total)}</b>\n'
    f'{tag("money")} {x["left_balance"]}: '
    f'<b>{price(new["balance"])}</b>\n\n'
    f'{x["order_id"]}: <code>{oid}</code>\n\n'
    'Your product has been delivered above.'
)

# The purchase result must be a NORMAL TEXT message.
# Do not edit the subcategory photo/caption.
    try:
        await cq.message.delete()
    except Exception:
        pass

    await bot.send_message(
    cq.from_user.id,
    success_text,
    parse_mode="HTML",
    reply_markup=purchase_success_kb(lang),
)

@router.callback_query(F.data.startswith('custom:'))
async def custom(cq, state):
    parts = cq.data.split(':')
    pid = parts[1]
    sid = parts[2] if len(parts) > 2 else ''
    await state.update_data(pid=pid, sid=sid, prompt_message_id=cq.message.message_id)
    await state.set_state(Qty.custom)
    await cq.answer()
    await edit_shop_message(
        cq,
        f'{tag("quantity")} <b>Custom Quantity</b>\n\nSend the quantity as a number.',
    )


@router.message(Qty.custom)
async def custom_msg(m, state, db, bot):
    d = await state.get_data()
    try:
        q = int((m.text or '').strip())
        assert q > 0
    except Exception:
        return await m.answer('❌ Enter a valid positive quantity.')
    try:
        await m.delete()
    except Exception:
        pass
    pid = d['pid']
    sid = d.get('sid', '')
    p = await product(db, pid)
    u = await get_user(db, m.from_user.id)
    lang = await get_lang(db, m.from_user.id)
    x = T[lang]
    if not p:
        await state.clear()
        return await edit_prompt(bot, m.chat.id, d.get('prompt_message_id'), f'❌ {x["product_unavailable"]}')
    total = float(p['price']) * q
    if float(u.get('balance', 0)) < total:
        b = InlineKeyboardBuilder()
        b.row(btn(x['recharge'], callback_data='recharge', emoji_key='recharge', style='success'))
        b.row(btn(x['back'], callback_data=f'prod:{pid}:{sid}', emoji_key='back', style='danger'))
        await edit_prompt(
            bot, m.chat.id, d.get('prompt_message_id'),
            f'{tag("money")} <b>{x["insufficient"]}</b>\n\n{x["price"]}: {price(total)}',
            b.as_markup(),
        )
        return
    try:
        oid, new = await purchase(db, bot, m.from_user.id, p, q)
    except ValueError as e:
        await state.clear()
        return await edit_prompt(bot, m.chat.id, d.get('prompt_message_id'), f'❌ {str(e).replace("_", " ")}')
    await log_purchase(bot, {'product_name': p['name'], 'quantity': q, 'total': total}, {**u, 'balance': new['balance']}, new['balance'])
    try:
        await deliver_product(bot, m.from_user.id, p)
    except Exception:
        await bot.send_message(m.from_user.id, '⚠️ Payment succeeded, but delivery failed. Please contact support.')
    await state.clear()
    await edit_prompt(
        bot, m.chat.id, d.get('prompt_message_id'),
        f'{tag("success")} <b>{x["purchase_ok"]}</b>\n\n'
        f'{tag("stock")} {escape(p["name"])}\n'
        f'{tag("quantity")} {x["quantity"]}: {q}\n'
        f'{tag("amount")} {x["paid"]}: {price(total)}\n'
        f'{tag("money")} {x["left_balance"]}: {price(new["balance"])}\n\n'
        f'{x["order_id"]}: <code>{oid}</code>',
        home_kb(lang),
    )


@router.callback_query(F.data == 'search')
async def search(cq, state, db):
    await state.update_data(prompt_message_id=cq.message.message_id)
    await state.set_state(Qty.search)
    lang = await get_lang(db, cq.from_user.id)
    x = T[lang]
    await cq.answer()
    await edit_shop_message(
        cq,
        f'{tag("search")} <b>{x["search"]}</b>\n\n{x["search_prompt"]}',
        product_kb([], 'products', lang),
    )


@router.message(Qty.search)
async def search_msg(m, state, db, bot):
    d = await state.get_data()
    lang = await get_lang(db, m.from_user.id)
    x = T[lang]
    if m.text and m.text.strip() == '/cancel':
        await state.clear()
        try:
            await m.delete()
        except Exception:
            pass
        return await edit_prompt(bot, m.chat.id, d.get('prompt_message_id'), '❌ Cancelled.', home_kb(lang))
    query = (m.text or '').strip()
    try:
        await m.delete()
    except Exception:
        pass
    if not query:
        return await edit_prompt(
            bot, m.chat.id, d.get('prompt_message_id'),
            f'{tag("search")} <b>{x["search"]}</b>\n\n❌ {x["search_prompt"]}',
            product_kb([], 'products', lang),
        )
    await edit_prompt(
        bot, m.chat.id, d.get('prompt_message_id'),
        f'{tag("loading")} <b>Searching…</b>\n\n<code>{escape(query)}</code>',
    )
    ps = await search_products(db, query)
    await state.clear()
    if not ps:
        text = f'{tag("search")} <b>{x["search"]}</b>\n\n{x["no_products"]}'
    else:
        text = product_list(ps, lang)
    await edit_prompt(bot, m.chat.id, d.get('prompt_message_id'), text, product_kb(ps, 'products', lang))
