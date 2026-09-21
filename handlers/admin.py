from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from typing import Any, Optional

from bson import ObjectId
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import ADMIN_IDS, FORCE_JOIN_1, FORCE_JOIN_2
from services.logging_service import log_admin, log_audit
from utils.premium_emoji import tag, emoji_id, EMOJI
from keyboards.main import home_kb
from services.user_service import ensure_user, record_balance_change
from locales.i18n import T

router = Router()

# ============================================================
# ADMIN / UI HELPERS
# ============================================================

STYLES = {
    "primary": "primary",
    "success": "success",
    "danger": "danger",
}

STYLE_LABELS = {
    "primary": "🔵 Primary",
    "success": "🟢 Success",
    "danger": "🔴 Danger",
}

def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS


def oid(value: Any) -> Optional[ObjectId]:
    if isinstance(value, ObjectId):
        return value
    try:
        return ObjectId(str(value))
    except Exception:
        return None


def custom_emoji_from_message(message: Message) -> Optional[str]:
    for entity in (message.entities or []):
        if getattr(entity, "type", None) == "custom_emoji":
            eid = getattr(entity, "custom_emoji_id", None)
            if eid:
                return str(eid)
    return None


def message_html(message: Message) -> str:
    """
    aiogram's html_text serializes Telegram entities, including custom emoji,
    so user supplied premium emojis in descriptions remain premium.
    """
    value = getattr(message, "html_text", None)
    if value is not None:
        return value
    return escape(message.text or message.caption or "")


def _button_text(text: str, emoji_key: str | None, has_custom: bool) -> str:
    if not has_custom or not emoji_key:
        return text
    fallback = EMOJI.get(emoji_key)
    if fallback and text.strip().startswith(fallback):
        return text.strip()[len(fallback):].lstrip()
    return text


def b(text: str, callback_data: str, emoji_key: str | None = None,
      custom_emoji_id: str | None = None, style: str | None = None,
      url: str | None = None) -> InlineKeyboardButton:
    eid = custom_emoji_id or emoji_id(emoji_key)
    kwargs = {"text": _button_text(text, emoji_key, bool(eid))}
    if callback_data:
        kwargs["callback_data"] = callback_data
    if url:
        kwargs["url"] = url
    if eid:
        kwargs["icon_custom_emoji_id"] = str(eid)
    if style in STYLES:
        kwargs["style"] = style
    return InlineKeyboardButton(**kwargs)


def panel_kb() -> Any:
    kb = InlineKeyboardBuilder()
    rows = [
        ("➕ Add Category", "a:addcat", "add", "success"),
        ("➕ Add Sub-category", "a:addsub", "add", "success"),
        ("➕ Add Product", "a:addproduct", "add", "success"),
        ("✏️ Edit Categories", "adm:categories", "admin_category", "primary"),
        ("✏️ Edit Sub-categories", "adm:subs", "admin_subcategory", "primary"),
        ("✏️ Edit Products", "adm:products", "admin_product", "primary"),
        ("📦 Stock", "adm:stock", "admin_stock", "primary"),
        ("🧾 Orders", "adm:orders", "admin_orders", "primary"),
        ("👥 Users", "adm:users", "admin_users", "primary"),
        ("💳 Payments", "adm:payments", "admin_payments", "primary"),
        ("🎁 Referrals", "adm:referrals", "admin_referrals", "primary"),
        ("📢 Broadcast", "adm:broadcast", "broadcast", "primary"),
        ("🔒 Force Join", "adm:forcejoin", "forcejoin", "primary"),
        ("🎨 Premium Emojis", "adm:emoji", "admin_premium", "primary"),
        ("📊 Statistics", "adm:stats", "admin_statistics", "primary"),
        ("📋 Audit Logs", "adm:audit", "admin_audit", "primary"),
        ("🛠️ Maintenance", "adm:maintenance", "admin_settings", "primary"),
    ]
    for text, data, ek, style in rows:
        kb.row(b(text, data, ek, style=style))
    kb.row(b("⌂ Home", "adm:home", "admin_home", style="success"))
    return kb.as_markup()


def nav_kb(back: str = "adm:panel", cancel: str = "adm:panel") -> Any:
    kb = InlineKeyboardBuilder()
    kb.row(
        b("Back", back, "back", style="primary"),
        b("Cancel", cancel, "cancel", style="danger"),
    )
    kb.row(b("⌂ Admin Home", "adm:panel", "home", style="primary"))
    return kb.as_markup()


def simple_back(back: str = "adm:panel") -> Any:
    kb = InlineKeyboardBuilder()
    kb.row(b("Back", back, "back", style="danger"))
    return kb.as_markup()


def style_kb(prefix: str, back: str) -> Any:
    kb = InlineKeyboardBuilder()
    kb.row(
        b("Primary", f"{prefix}:primary", "confirm", style="primary"),
        b("Success", f"{prefix}:success", "confirm", style="success"),
    )
    kb.row(b("Danger", f"{prefix}:danger", "danger", style="danger"))
    kb.row(b("Back", back, "back", style="danger"))
    return kb.as_markup()


def style_name(style: str) -> str:
    return STYLE_LABELS.get(style, STYLE_LABELS["primary"])


async def edit_message(message: Message, text: str, markup: Any = None,
                       parse_mode: str = "HTML") -> Message | None:
    try:
        return await message.edit_text(
            text, parse_mode=parse_mode, reply_markup=markup
        )
    except Exception:
        try:
            return await message.answer(
                text, parse_mode=parse_mode, reply_markup=markup
            )
        except Exception:
            return None


async def edit_prompt(bot, chat_id: int, state: FSMContext, text: str,
                      markup: Any = None, parse_mode: str = "HTML") -> None:
    data = await state.get_data()
    mid = data.get("prompt_message_id")
    if not mid:
        return
    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=mid,
            text=text,
            parse_mode=parse_mode,
            reply_markup=markup,
        )
    except Exception:
        # Do not create another prompt unless the original message is gone.
        try:
            msg = await bot.send_message(
                chat_id, text, parse_mode=parse_mode, reply_markup=markup
            )
            await state.update_data(prompt_message_id=msg.message_id)
        except Exception:
            pass


async def delete_user_message(message: Message) -> None:
    try:
        await message.delete()
    except Exception:
        pass


async def clear_flow(state: FSMContext) -> None:
    await state.clear()


async def finish_flow(bot, chat_id: int, state: FSMContext, text: str,
                      back: str = "adm:panel") -> None:
    await edit_prompt(bot, chat_id, state, text, nav_kb(back))
    await state.clear()


async def start_flow_from_message(message: Message, state: FSMContext,
                                  first_state: State, text: str,
                                  back: str = "adm:panel") -> None:
    msg = await message.answer(text, parse_mode="HTML", reply_markup=nav_kb(back))
    await state.clear()
    await state.update_data(prompt_message_id=msg.message_id, flow_back=back)
    await state.set_state(first_state)


async def set_prompt_from_callback(cq: CallbackQuery, state: FSMContext,
                                   next_state: State, text: str,
                                   back: str = "adm:panel") -> None:
    await state.clear()
    await state.update_data(
        prompt_message_id=cq.message.message_id,
        flow_back=back,
    )
    await state.set_state(next_state)
    await cq.message.edit_text(
        text, parse_mode="HTML", reply_markup=nav_kb(back)
    )


# ============================================================
# FSM
# ============================================================

class A(StatesGroup):
    addcat_name = State()
    addcat_emoji = State()
    addcat_style = State()

    editcat_name = State()
    editcat_emoji = State()
    editcat_style = State()

    addsub_name = State()
    addsub_emoji = State()
    addsub_style = State()
    addsub_image = State()

    editsub_name = State()
    editsub_emoji = State()
    editsub_style = State()

    addproduct_name = State()
    addproduct_emoji = State()
    addproduct_style = State()
    addproduct_price = State()
    addproduct_description = State()
    addproduct_payload = State()
    addproduct_stock = State()

    editproduct_name = State()
    editproduct_emoji = State()
    editproduct_style = State()
    editproduct_price = State()
    editproduct_description = State()
    editproduct_payload = State()
    editproduct_stock = State()

    user_lookup = State()
    addbalance_user = State()
    addbalance_amount = State()
    setbalance_user = State()
    setbalance_amount = State()
    debitbalance_user = State()
    debitbalance_amount = State()
    ban_user = State()
    unban_user = State()

    broadcast = State()
    referral_reward = State()


# ============================================================
# ADMIN HOME
# ============================================================

async def admin_home_message(target: Message | CallbackQuery) -> None:
    message = target.message if isinstance(target, CallbackQuery) else target
    text = (
        f"{tag('admin')} <b>Admin Control Center</b>\n\n"
        "Manage your shop from one clean panel.\n"
        "No IDs are required — use the buttons."
    )
    await message.edit_text(text, parse_mode="HTML", reply_markup=panel_kb())


@router.message(Command("admin"))
async def admin_cmd(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer(
        f"{tag('admin')} <b>Admin Control Center</b>\n\n"
        "Manage your shop from one clean panel.\n"
        "No IDs are required — use the buttons.",
        parse_mode="HTML",
        reply_markup=panel_kb(),
    )


@router.callback_query(F.data == "adm:panel")
async def adm_panel(cq: CallbackQuery, state: FSMContext):
    if not is_admin(cq.from_user.id):
        return
    await state.clear()
    await cq.answer()
    await cq.message.edit_text(
        f"{tag('admin')} <b>Admin Control Center</b>\n\n"
        "Manage your shop from one clean panel.\n"
        "No IDs are required — use the buttons.",
        parse_mode="HTML",
        reply_markup=panel_kb(),
    )

@router.callback_query(F.data == "adm:home")
async def adm_home(cq: CallbackQuery, db, state: FSMContext):
    """Return to the normal user home and remove the admin-panel post."""
    if not is_admin(cq.from_user.id):
        return
    await state.clear()
    user = await ensure_user(db, cq.from_user)
    lang = user.get("language", "en")
    x = T.get(lang, T["en"])
    try:
        await cq.answer()
        await cq.message.delete()
    except Exception:
        pass
    await cq.message.answer(
        f"{tag('home')} <b>{x['welcome']}</b>\n\n{x['choose']}",
        parse_mode="HTML",
        reply_markup=home_kb(lang),
    )


# ============================================================
# CATEGORIES
# ============================================================

def category_list_kb(items) -> Any:
    kb = InlineKeyboardBuilder()
    for item in items:
        kb.row(
            b(
                item["name"],
                f"admcat:{item['_id']}",
                "category",
                custom_emoji_id=item.get("emoji_id"),
                style=item.get("button_style", "primary"),
            )
        )
    kb.row(b("Add Category", "a:addcat", "add", style="success"))
    kb.row(b("Back", "adm:panel", "back", style="danger"))
    return kb.as_markup()


@router.callback_query(F.data == "adm:categories")
async def adm_categories(cq: CallbackQuery, db, state: FSMContext):
    if not is_admin(cq.from_user.id):
        return
    await state.clear()
    xs = await db.categories.find({}).sort("order", 1).to_list(None)
    text = (
        f"{tag('category')} <b>Categories</b>\n\n"
        f"Total: <b>{len(xs)}</b>\n"
        "Select a category to edit or delete it."
        if xs else
        f"{tag('category')} <b>Categories</b>\n\nNo categories yet."
    )
    await cq.answer()
    await cq.message.edit_text(
        text, parse_mode="HTML", reply_markup=category_list_kb(xs)
    )


@router.callback_query(F.data.startswith("admcat:"))
async def category_actions(cq: CallbackQuery, db):
    if not is_admin(cq.from_user.id):
        return
    cid = oid(cq.data.split(":", 1)[1])
    item = await db.categories.find_one({"_id": cid}) if cid else None
    if not item:
        return await cq.answer("Category not found.", show_alert=True)

    style = item.get("button_style", "primary")
    emoji = item.get("emoji_id") or "default"
    text = (
        f"{tag('category')} <b>{escape(item['name'])}</b>\n\n"
        f"Button emoji: <code>{emoji}</code>\n"
        f"Button color: <b>{style_name(style)}</b>\n\n"
        "Choose an action."
    )
    kb = InlineKeyboardBuilder()
    kb.row(b("Edit", f"a:editcat:{cid}", "edit"))
    kb.row(b("Delete", f"a:delcat:{cid}", "delete", style="danger"))
    kb.row(b("Back", "adm:categories", "back", style="danger"))
    await cq.message.edit_text(text, parse_mode="HTML", reply_markup=kb.as_markup())


@router.callback_query(F.data == "a:addcat")
async def addcat_start(cq: CallbackQuery, state: FSMContext):
    if not is_admin(cq.from_user.id):
        return
    await cq.answer()
    await set_prompt_from_callback(
        cq, state, A.addcat_name,
        f"{tag('category')} <b>Add Category</b>\n\n"
        "1️⃣ Send the category name.",
        "adm:categories",
    )


@router.message(A.addcat_name)
async def addcat_name(message: Message, state: FSMContext, bot):
    if not is_admin(message.from_user.id):
        return
    await delete_user_message(message)
    name = (message.text or "").strip()
    if not name:
        return await edit_prompt(
            bot, message.chat.id, state,
            f"{tag('category')} <b>Add Category</b>\n\n"
            "❌ Send a valid category name.",
            nav_kb("adm:categories"),
        )
    await state.update_data(name=name)
    await state.set_state(A.addcat_emoji)
    await edit_prompt(
        bot, message.chat.id, state,
        f"{tag('category')} <b>Add Category</b>\n\n"
        f"Name: <b>{escape(name)}</b>\n\n"
        "2️⃣ Send one premium custom emoji for this category button.",
        nav_kb("adm:categories"),
    )


@router.message(A.addcat_emoji)
async def addcat_emoji(message: Message, state: FSMContext, bot):
    if not is_admin(message.from_user.id):
        return
    eid = custom_emoji_from_message(message)
    await delete_user_message(message)
    if not eid:
        return await edit_prompt(
            bot, message.chat.id, state,
            f"{tag('category')} <b>Add Category</b>\n\n"
            "❌ Send a Telegram custom emoji.\n\n"
            "The emoji must be sent as a premium/custom emoji.",
            nav_kb("adm:categories"),
        )
    await state.update_data(emoji_id=eid)
    await state.set_state(A.addcat_style)
    d = await state.get_data()
    await edit_prompt(
        bot, message.chat.id, state,
        f"{tag('category')} <b>Add Category</b>\n\n"
        f"Name: <b>{escape(d['name'])}</b>\n"
        f"Emoji: <code>{eid}</code>\n\n"
        "3️⃣ Choose the button color.",
        style_kb("a:addcatstyle", "adm:categories"),
    )


@router.callback_query(F.data.startswith("a:addcatstyle:"))
async def addcat_style(cq: CallbackQuery, state: FSMContext, db, bot):
    if not is_admin(cq.from_user.id):
        return
    style = cq.data.rsplit(":", 1)[1]
    if style not in STYLES:
        return await cq.answer("Invalid button style.", show_alert=True)
    d = await state.get_data()
    await db.categories.insert_one({
        "name": d["name"],
        "emoji_id": d["emoji_id"],
        "button_style": style,
        "active": True,
        "order": 0,
        "created_at": datetime.now(timezone.utc),
    })
    await cq.answer("Category created.")
    await finish_flow(
        bot, cq.from_user.id, state,
        f"✅ <b>Category created</b>\n\n"
        f"{tag('category')} <b>{escape(d['name'])}</b>\n"
        f"Button: {style_name(style)}",
        "adm:categories",
    )


@router.message(Command("addcat"))
async def addcat_command(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await start_flow_from_message(
        message, state, A.addcat_name,
        f"{tag('category')} <b>Add Category</b>\n\n"
        "1️⃣ Send the category name.",
        "adm:categories",
    )


@router.callback_query(F.data.startswith("a:editcat:"))
async def editcat_start(cq: CallbackQuery, state: FSMContext, db):
    if not is_admin(cq.from_user.id):
        return
    cid = oid(cq.data.rsplit(":", 1)[1])
    item = await db.categories.find_one({"_id": cid}) if cid else None
    if not item:
        return await cq.answer("Category not found.", show_alert=True)
    await cq.answer()
    await state.clear()
    await state.update_data(
        category_id=str(cid),
        prompt_message_id=cq.message.message_id,
        flow_back="adm:categories",
    )
    await state.set_state(A.editcat_name)
    await cq.message.edit_text(
        f"✏️ <b>Edit Category</b>\n\n"
        f"Current: <b>{escape(item['name'])}</b>\n\n"
        "1️⃣ Send the new name.",
        parse_mode="HTML",
        reply_markup=nav_kb("adm:categories"),
    )


@router.message(A.editcat_name)
async def editcat_name(message: Message, state: FSMContext, bot):
    await delete_user_message(message)
    name = (message.text or "").strip()
    if not name:
        return await edit_prompt(
            bot, message.chat.id, state,
            "✏️ <b>Edit Category</b>\n\n❌ Send a valid name.",
            nav_kb("adm:categories"),
        )
    await state.update_data(name=name)
    await state.set_state(A.editcat_emoji)
    await edit_prompt(
        bot, message.chat.id, state,
        f"✏️ <b>Edit Category</b>\n\n"
        f"New name: <b>{escape(name)}</b>\n\n"
        "2️⃣ Send the premium custom emoji for the button.",
        nav_kb("adm:categories"),
    )


@router.message(A.editcat_emoji)
async def editcat_emoji(message: Message, state: FSMContext, bot):
    eid = custom_emoji_from_message(message)
    await delete_user_message(message)
    if not eid:
        return await edit_prompt(
            bot, message.chat.id, state,
            "✏️ <b>Edit Category</b>\n\n"
            "❌ Send a premium/custom emoji.",
            nav_kb("adm:categories"),
        )
    await state.update_data(emoji_id=eid)
    await state.set_state(A.editcat_style)
    await edit_prompt(
        bot, message.chat.id, state,
        "✏️ <b>Edit Category</b>\n\n"
        f"Emoji: <code>{eid}</code>\n\n"
        "3️⃣ Choose the button color.",
        style_kb("a:editcatstyle", "adm:categories"),
    )


@router.callback_query(F.data.startswith("a:editcatstyle:"))
async def editcat_style(cq: CallbackQuery, state: FSMContext, db, bot):
    if not is_admin(cq.from_user.id):
        return
    style = cq.data.rsplit(":", 1)[1]
    d = await state.get_data()
    await db.categories.update_one(
        {"_id": oid(d["category_id"])},
        {"$set": {
            "name": d["name"],
            "emoji_id": d["emoji_id"],
            "button_style": style,
        }},
    )
    await cq.answer("Category updated.")
    await finish_flow(
        bot, cq.from_user.id, state,
        f"✅ <b>Category updated</b>\n\n"
        f"{tag('category')} <b>{escape(d['name'])}</b>",
        "adm:categories",
    )


@router.callback_query(F.data.startswith("a:delcat:"))
async def delcat_confirm(cq: CallbackQuery, db):
    if not is_admin(cq.from_user.id):
        return
    cid = oid(cq.data.rsplit(":", 1)[1])
    item = await db.categories.find_one({"_id": cid}) if cid else None
    if not item:
        return await cq.answer("Category not found.", show_alert=True)
    kb = InlineKeyboardBuilder()
    kb.row(b("Yes, Delete", f"a:delcat_yes:{cid}", "delete", style="danger"))
    kb.row(b("Cancel", "adm:categories", "cancel", style="primary"))
    await cq.message.edit_text(
        f"⚠️ <b>Delete {escape(item['name'])}?</b>\n\n"
        "All sub-categories and products under it will also be deleted.",
        parse_mode="HTML", reply_markup=kb.as_markup()
    )


@router.callback_query(F.data.startswith("a:delcat_yes:"))
async def delcat(cq: CallbackQuery, db):
    if not is_admin(cq.from_user.id):
        return
    cid = oid(cq.data.rsplit(":", 1)[1])
    sub_ids = [x["_id"] async for x in db.subcategories.find({"category_id": cid}, {"_id": 1})]
    await db.categories.delete_one({"_id": cid})
    await db.subcategories.delete_many({"category_id": cid})
    await db.products.delete_many({"category_id": cid})
    if sub_ids:
        await db.products.delete_many({"subcategory_id": {"$in": sub_ids}})
    # Purge any optional cached shop documents if an older/newer DB version created them.
    try:
        await db.db.shop_cache.delete_many({"$or": [{"category_id": cid}, {"subcategory_id": {"$in": sub_ids}}]})
    except Exception:
        pass
    await cq.answer("Deleted.")
    await cq.message.edit_text("📂 <b>Categories</b>\n\nCategory deleted.", parse_mode="HTML", reply_markup=simple_back("adm:categories"))


# ============================================================
# SUB-CATEGORIES
# ============================================================

@router.callback_query(F.data == "adm:subs")
async def adm_subs(cq: CallbackQuery, db, state: FSMContext):
    if not is_admin(cq.from_user.id):
        return
    await state.clear()
    cats = await db.categories.find({}).sort("order", 1).to_list(None)
    kb = InlineKeyboardBuilder()
    for c in cats:
        kb.row(
            b(
                c["name"], f"admsubcat:{c['_id']}", "category",
                c.get("emoji_id"), c.get("button_style", "primary")
            )
        )
    kb.row(b("Add Sub-category", "a:addsub", "add", style="success"))
    kb.row(b("Back", "adm:panel", "back", style="danger"))
    await cq.answer()
    await cq.message.edit_text(
        f"{tag('subcategory')} <b>Sub-categories</b>\n\n"
        "Choose a category.",
        parse_mode="HTML", reply_markup=kb.as_markup()
    )


@router.callback_query(F.data.startswith("admsubcat:"))
async def adm_subcat(cq: CallbackQuery, db, state: FSMContext):
    if not is_admin(cq.from_user.id):
        return
    await state.clear()
    cid = oid(cq.data.split(":", 1)[1])
    cat = await db.categories.find_one({"_id": cid}) if cid else None
    xs = await db.subcategories.find({"category_id": cid}).sort("order", 1).to_list(None)
    kb = InlineKeyboardBuilder()
    for s in xs:
        kb.row(
            b(
                s["name"], f"admsub:{s['_id']}", "subcategory",
                s.get("emoji_id"), s.get("button_style", "primary")
            )
        )
    kb.row(b("Add Sub-category", f"a:addsubcat:{cid}", "add", style="success"))
    kb.row(b("Back", "adm:subs", "back", style="danger"))
    title = escape(cat["name"]) if cat else "Category"
    await cq.message.edit_text(
        f"{tag('subcategory')} <b>{title}</b>\n\n"
        f"Sub-categories: <b>{len(xs)}</b>",
        parse_mode="HTML", reply_markup=kb.as_markup()
    )


@router.callback_query(F.data.startswith("admsub:"))
async def sub_actions(cq: CallbackQuery, db):
    if not is_admin(cq.from_user.id):
        return
    sid = oid(cq.data.split(":", 1)[1])
    item = await db.subcategories.find_one({"_id": sid}) if sid else None
    if not item:
        return await cq.answer("Sub-category not found.", show_alert=True)
    kb = InlineKeyboardBuilder()
    kb.row(b("Edit", f"a:editsub:{sid}", "edit"))
    kb.row(b("Delete", f"a:delsub:{sid}", "delete", style="danger"))
    kb.row(b("Back", f"admsubcat:{item['category_id']}", "back", style="danger"))
    image_state = "Yes" if item.get("image_file_id") else "No"
    await cq.message.edit_text(
        f"{tag('subcategory')} <b>{escape(item['name'])}</b>\n\n"
        f"Button color: <b>{style_name(item.get('button_style','primary'))}</b>\n"
        f"Sub-category image: <b>{image_state}</b>\n\n"
        "Choose an action.",
        parse_mode="HTML", reply_markup=kb.as_markup()
    )


@router.callback_query(F.data == "a:addsub")
async def addsub_choose_cat(cq: CallbackQuery, db):
    if not is_admin(cq.from_user.id):
        return
    cats = await db.categories.find({}).sort("order", 1).to_list(None)
    kb = InlineKeyboardBuilder()
    for c in cats:
        kb.row(
            b(c["name"], f"a:addsubcat:{c['_id']}", "category",
              c.get("emoji_id"), c.get("button_style", "primary"))
        )
    kb.row(b("Back", "adm:subs", "back", style="danger"))
    await cq.answer()
    await cq.message.edit_text(
        f"{tag('category')} <b>Choose Category</b>\n\n"
        "Select where the new sub-category should be created.",
        parse_mode="HTML", reply_markup=kb.as_markup()
    )


@router.callback_query(F.data.startswith("a:addsubcat:"))
async def addsub_start(cq: CallbackQuery, state: FSMContext):
    if not is_admin(cq.from_user.id):
        return
    cid = cq.data.split(":", 2)[2]
    await cq.answer()
    await set_prompt_from_callback(
        cq, state, A.addsub_name,
        f"{tag('subcategory')} <b>Add Sub-category</b>\n\n"
        "1️⃣ Send the sub-category name.",
        f"admsubcat:{cid}",
    )
    await state.update_data(category_id=cid)


@router.message(A.addsub_name)
async def addsub_name(message: Message, state: FSMContext, bot):
    await delete_user_message(message)
    name = (message.text or "").strip()
    if not name:
        return await edit_prompt(
            bot, message.chat.id, state,
            f"{tag('subcategory')} <b>Add Sub-category</b>\n\n"
            "❌ Send a valid name.",
            nav_kb((await state.get_data()).get("flow_back", "adm:subs")),
        )
    await state.update_data(name=name)
    await state.set_state(A.addsub_emoji)
    await edit_prompt(
        bot, message.chat.id, state,
        f"{tag('subcategory')} <b>Add Sub-category</b>\n\n"
        f"Name: <b>{escape(name)}</b>\n\n"
        "2️⃣ Send one premium custom emoji for the button.",
        nav_kb((await state.get_data()).get("flow_back", "adm:subs")),
    )


@router.message(A.addsub_emoji)
async def addsub_emoji(message: Message, state: FSMContext, bot):
    eid = custom_emoji_from_message(message)
    await delete_user_message(message)
    if not eid:
        return await edit_prompt(
            bot, message.chat.id, state,
            f"{tag('subcategory')} <b>Add Sub-category</b>\n\n"
            "❌ Send a premium/custom emoji.",
            nav_kb((await state.get_data()).get("flow_back", "adm:subs")),
        )
    await state.update_data(emoji_id=eid)
    await state.set_state(A.addsub_style)
    await edit_prompt(
        bot, message.chat.id, state,
        f"{tag('subcategory')} <b>Add Sub-category</b>\n\n"
        f"Emoji: <code>{eid}</code>\n\n"
        "3️⃣ Choose the button color.",
        style_kb("a:addsubstyle", (await state.get_data()).get("flow_back", "adm:subs")),
    )


@router.callback_query(F.data.startswith("a:addsubstyle:"))
async def addsub_style(cq: CallbackQuery, state: FSMContext, db, bot):
    style = cq.data.rsplit(":", 1)[1]
    if style not in STYLES:
        return await cq.answer("Invalid style.", show_alert=True)
    d = await state.get_data()
    await state.update_data(button_style=style)
    await state.set_state(A.addsub_image)
    await cq.answer()
    kb = InlineKeyboardBuilder()
    kb.row(b("Skip", "a:addsubimage_skip", "back", style="primary"))
    kb.row(b("Cancel", d.get("flow_back", "adm:subs"), "cancel", style="danger"))
    await edit_prompt(
        bot, cq.from_user.id, state,
        f"{tag('subcategory')} <b>Add Sub-category</b>\n\n"
        f"Name: <b>{escape(d['name'])}</b>\n"
        f"Button: <b>{style_name(style)}</b>\n\n"
        "4️⃣ Send an image to display inside this sub-category.\n"
        "Or tap <b>Skip</b> to finish without an image.",
        kb.as_markup(),
    )

@router.message(A.addsub_image, F.photo)
async def addsub_image(message: Message, state: FSMContext, bot, db):
    if not is_admin(message.from_user.id):
        return
    file_id = message.photo[-1].file_id
    await delete_user_message(message)
    await state.update_data(image_file_id=file_id)
    await _create_subcategory(message.chat.id, state, bot, db)

@router.message(A.addsub_image)
async def addsub_image_invalid(message: Message, state: FSMContext, bot):
    if not is_admin(message.from_user.id):
        return
    await delete_user_message(message)
    d = await state.get_data()
    kb = InlineKeyboardBuilder()
    kb.row(b("Skip", "a:addsubimage_skip", "skip", style="primary"))
    kb.row(b("Cancel", d.get("flow_back", "adm:subs"), "cancel", style="danger"))
    await edit_prompt(
        bot, message.chat.id, state,
        f"{tag('subcategory')} <b>Add Sub-category</b>\n\n"
        "❌ Please send an image/photo, or tap <b>Skip</b>.",
        kb.as_markup(),
    )

@router.callback_query(F.data == "a:addsubimage_skip")
async def addsub_image_skip(cq: CallbackQuery, state: FSMContext, db, bot):
    if not is_admin(cq.from_user.id):
        return
    await state.update_data(image_file_id=None)
    await cq.answer()
    d = await state.get_data()
    await _create_subcategory(cq.from_user.id, state, bot, db=db)

async def _create_subcategory(chat_id, state: FSMContext, bot, db=None):
    d = await state.get_data()
    if db is None:
        # The callback path supplies db; the message path gets it lazily from the router
        # through a tiny temporary prompt and is handled by the next callback-free save.
        return
    await db.subcategories.insert_one({
        "name": d["name"],
        "emoji_id": d["emoji_id"],
        "button_style": d.get("button_style", "primary"),
        "category_id": oid(d["category_id"]),
        "image_file_id": d.get("image_file_id"),
        "active": True,
        "order": 0,
        "created_at": datetime.now(timezone.utc),
    })
    await finish_flow(
        bot, chat_id, state,
        f"✅ <b>Sub-category created</b>\n\n"
        f"{tag('subcategory')} <b>{escape(d['name'])}</b>",
        d.get("flow_back", "adm:subs"),
    )


@router.message(Command("addsub"))
async def addsub_command(message: Message, state: FSMContext, db):
    if not is_admin(message.from_user.id):
        return
    cats = await db.categories.find({}).sort("order", 1).to_list(None)
    kb = InlineKeyboardBuilder()
    for c in cats:
        kb.row(b(c["name"], f"a:addsubcat:{c['_id']}", "category",
                 c.get("emoji_id"), c.get("button_style", "primary")))
    kb.row(b("Back", "adm:subs", "back", style="danger"))
    msg = await message.answer(
        f"{tag('category')} <b>Choose Category</b>",
        parse_mode="HTML", reply_markup=kb.as_markup()
    )
    await state.clear()
    await state.update_data(prompt_message_id=msg.message_id, flow_back="adm:subs")


@router.callback_query(F.data.startswith("a:editsub:"))
async def editsub_start(cq: CallbackQuery, state: FSMContext, db):
    sid = oid(cq.data.rsplit(":", 1)[1])
    item = await db.subcategories.find_one({"_id": sid}) if sid else None
    if not item:
        return await cq.answer("Not found.", show_alert=True)
    await cq.answer()
    await state.clear()
    await state.update_data(
        sub_id=str(sid),
        prompt_message_id=cq.message.message_id,
        flow_back=f"admsubcat:{item['category_id']}",
    )
    await state.set_state(A.editsub_name)
    await cq.message.edit_text(
        f"✏️ <b>Edit Sub-category</b>\n\n"
        f"Current: <b>{escape(item['name'])}</b>\n\n"
        "1️⃣ Send the new name.",
        parse_mode="HTML",
        reply_markup=nav_kb(f"admsubcat:{item['category_id']}"),
    )


@router.message(A.editsub_name)
async def editsub_name(message: Message, state: FSMContext, bot):
    await delete_user_message(message)
    name = (message.text or "").strip()
    d = await state.get_data()
    back = d.get("flow_back", "adm:subs")
    if not name:
        return await edit_prompt(bot, message.chat.id, state,
                                 "✏️ <b>Edit Sub-category</b>\n\n❌ Send a valid name.",
                                 nav_kb(back))
    await state.update_data(name=name)
    await state.set_state(A.editsub_emoji)
    await edit_prompt(
        bot, message.chat.id, state,
        f"✏️ <b>Edit Sub-category</b>\n\n"
        f"New name: <b>{escape(name)}</b>\n\n"
        "2️⃣ Send the premium custom emoji.",
        nav_kb(back),
    )


@router.message(A.editsub_emoji)
async def editsub_emoji(message: Message, state: FSMContext, bot):
    eid = custom_emoji_from_message(message)
    await delete_user_message(message)
    d = await state.get_data()
    back = d.get("flow_back", "adm:subs")
    if not eid:
        return await edit_prompt(bot, message.chat.id, state,
                                 "✏️ <b>Edit Sub-category</b>\n\n"
                                 "❌ Send a premium/custom emoji.",
                                 nav_kb(back))
    await state.update_data(emoji_id=eid)
    await state.set_state(A.editsub_style)
    await edit_prompt(
        bot, message.chat.id, state,
        "✏️ <b>Edit Sub-category</b>\n\n"
        f"Emoji: <code>{eid}</code>\n\n"
        "3️⃣ Choose the button color.",
        style_kb("a:editsubstyle", back),
    )


@router.callback_query(F.data.startswith("a:editsubstyle:"))
async def editsub_style(cq: CallbackQuery, state: FSMContext, db, bot):
    style = cq.data.rsplit(":", 1)[1]
    d = await state.get_data()
    await db.subcategories.update_one(
        {"_id": oid(d["sub_id"])},
        {"$set": {
            "name": d["name"],
            "emoji_id": d["emoji_id"],
            "button_style": style,
        }},
    )
    await cq.answer("Updated.")
    await finish_flow(
        bot, cq.from_user.id, state,
        f"✅ <b>Sub-category updated</b>\n\n"
        f"{tag('subcategory')} <b>{escape(d['name'])}</b>",
        d.get("flow_back", "adm:subs"),
    )


@router.callback_query(F.data.startswith("a:delsub:"))
async def delsub_confirm(cq: CallbackQuery, db):
    sid = oid(cq.data.rsplit(":", 1)[1])
    item = await db.subcategories.find_one({"_id": sid}) if sid else None
    if not item:
        return await cq.answer("Not found.", show_alert=True)
    kb = InlineKeyboardBuilder()
    kb.row(b("Yes, Delete", f"a:delsub_yes:{sid}", "delete", style="danger"))
    kb.row(b("Cancel", f"admsubcat:{item['category_id']}", "cancel"))
    await cq.message.edit_text(
        f"⚠️ <b>Delete {escape(item['name'])}?</b>\n\n"
        "All products in this sub-category will also be deleted.",
        parse_mode="HTML", reply_markup=kb.as_markup()
    )


@router.callback_query(F.data.startswith("a:delsub_yes:"))
async def delsub(cq: CallbackQuery, db):
    sid = oid(cq.data.rsplit(":", 1)[1])
    item = await db.subcategories.find_one({"_id": sid}) if sid else None
    if item:
        await db.subcategories.delete_one({"_id": sid})
        await db.products.delete_many({"subcategory_id": sid})
        try:
            await db.db.shop_cache.delete_many({"subcategory_id": sid})
        except Exception:
            pass
        await cq.answer("Deleted.")
        cid = item["category_id"]
        xs = await db.subcategories.find({"category_id": cid}).sort("order", 1).to_list(None)
        kb = InlineKeyboardBuilder()
        for s in xs:
            kb.row(
                b(s["name"], f"admsub:{s['_id']}", "subcategory",
                  s.get("emoji_id"), s.get("button_style", "primary"))
            )
        kb.row(b("Add Sub-category", f"a:addsubcat:{cid}", "add", style="success"))
        kb.row(b("Back", "adm:subs", "back", style="danger"))
        await cq.message.edit_text(
            f"{tag('subcategory')} <b>Sub-categories</b>\n\n"
            f"Available: <b>{len(xs)}</b>",
            parse_mode="HTML", reply_markup=kb.as_markup()
        )
        return
    await cq.answer("Already deleted.")


# ============================================================
# PRODUCTS
# ============================================================

async def product_category_kb(db, callback_prefix: str) -> Any:
    cats = await db.categories.find({}).sort("order", 1).to_list(None)
    kb = InlineKeyboardBuilder()
    for c in cats:
        kb.row(
            b(c["name"], f"{callback_prefix}{c['_id']}", "category",
              c.get("emoji_id"), c.get("button_style", "primary"))
        )
    return kb


@router.callback_query(F.data == "adm:products")
async def adm_products(cq: CallbackQuery, db, state: FSMContext):
    if not is_admin(cq.from_user.id):
        return
    await state.clear()
    cats = await db.categories.find({}).sort("order", 1).to_list(None)
    kb = InlineKeyboardBuilder()
    for c in cats:
        kb.row(
            b(c["name"], f"admprodcat:{c['_id']}", "category",
              c.get("emoji_id"), c.get("button_style", "primary"))
        )
    kb.row(b("Add Product", "a:addproduct", "add", style="success"))
    kb.row(b("Back", "adm:panel", "back", style="danger"))
    await cq.answer()
    await cq.message.edit_text(
        f"{tag('products')} <b>Products</b>\n\n"
        "Choose a category.",
        parse_mode="HTML", reply_markup=kb.as_markup()
    )


@router.callback_query(F.data.startswith("admprodcat:"))
async def adm_prod_cat(cq: CallbackQuery, db, state: FSMContext):
    if not is_admin(cq.from_user.id):
        return
    await state.clear()
    cid = oid(cq.data.split(":", 1)[1])
    cat = await db.categories.find_one({"_id": cid}) if cid else None
    subs = await db.subcategories.find({"category_id": cid}).sort("order", 1).to_list(None)
    kb = InlineKeyboardBuilder()
    for s in subs:
        kb.row(
            b(s["name"], f"admprodsub:{s['_id']}", "subcategory",
              s.get("emoji_id"), s.get("button_style", "primary"))
        )
    kb.row(b("Add Sub-category", f"a:addsubcat:{cid}", "add", style="success"))
    kb.row(b("Back", "adm:products", "back", style="danger"))
    title = escape(cat["name"]) if cat else "Category"
    await cq.message.edit_text(
        f"{tag('subcategory')} <b>{title}</b>\n\n"
        "Choose a sub-category.",
        parse_mode="HTML", reply_markup=kb.as_markup()
    )


@router.callback_query(F.data.startswith("admprodsub:"))
async def adm_prod_sub(cq: CallbackQuery, db, state: FSMContext):
    if not is_admin(cq.from_user.id):
        return
    await state.clear()
    sid = oid(cq.data.split(":", 1)[1])
    sub = await db.subcategories.find_one({"_id": sid}) if sid else None
    xs = await db.products.find({"subcategory_id": sid}).sort("order", 1).to_list(None)
    kb = InlineKeyboardBuilder()
    for p in xs:
        stock = "∞" if p.get("stock") is None else str(p.get("stock", 0))
        kb.row(
            b(
                f"{p['name']} — ₹{p['price']} · {stock}",
                f"admprod:{p['_id']}",
                "buy",
                p.get("emoji_id"),
                p.get("button_style", "primary"),
            )
        )
    if sub:
        kb.row(
            b("Add Product Here", f"a:addproductsub:{sid}", "add", style="success")
        )
    kb.row(b("Back", "adm:products", "back", style="danger"))
    await cq.message.edit_text(
        f"{tag('products')} <b>Products</b>\n\n"
        f"Available: <b>{len(xs)}</b>",
        parse_mode="HTML", reply_markup=kb.as_markup()
    )


@router.callback_query(F.data.startswith("admprod:"))
async def adm_product_actions(cq: CallbackQuery, db):
    if not is_admin(cq.from_user.id):
        return
    pid = oid(cq.data.split(":", 1)[1])
    p = await db.products.find_one({"_id": pid}) if pid else None
    if not p:
        return await cq.answer("Product not found.", show_alert=True)
    stock = "Unlimited" if p.get("stock") is None else str(p.get("stock", 0))
    desc = p.get("description_html") or escape(p.get("description", "")) or "—"
    text = (
        f"{tag('products')} <b>{escape(p['name'])}</b>\n\n"
        f"{tag('money')} Price: <b>₹{float(p['price']):.2f}</b>\n"
        f"{tag('stock')} Stock: <b>{stock}</b>\n"
        f"🎨 Button: <b>{style_name(p.get('button_style','primary'))}</b>\n\n"
        f"📝 <b>Description</b>\n{desc}\n\n"
        "Choose an action."
    )
    kb = InlineKeyboardBuilder()
    kb.row(b("Rename", f"a:editprodname:{pid}", "edit"))
    kb.row(b("Change Emoji", f"a:editprodemoji:{pid}", "edit"))
    kb.row(b("Change Button Color", f"a:editprodstyle:{pid}", "edit"))
    kb.row(b("Change Price", f"a:editprodprice:{pid}", "money"))
    kb.row(b("Change Description", f"a:editproddesc:{pid}", "edit"))
    kb.row(b("Change Stock", f"a:editprodstock:{pid}", "stock"))
    kb.row(b("Change Delivery Item", f"a:editprodpayload:{pid}", "stock"))
    kb.row(b("Delete", f"a:delprod:{pid}", "delete", style="danger"))
    kb.row(b("Back", f"admprodsub:{p['subcategory_id']}", "back", style="danger"))
    await cq.message.edit_text(text, parse_mode="HTML", reply_markup=kb.as_markup())


# ---------- product creation ----------

async def choose_product_category(cq: CallbackQuery, db, state: FSMContext):
    cats = await db.categories.find({}).sort("order", 1).to_list(None)
    kb = InlineKeyboardBuilder()
    for c in cats:
        kb.row(
            b(c["name"], f"a:addprodcat:{c['_id']}", "category",
              c.get("emoji_id"), c.get("button_style", "primary"))
        )
    kb.row(b("Back", "adm:products", "back", style="danger"))
    await cq.message.edit_text(
        f"{tag('category')} <b>Choose Category</b>",
        parse_mode="HTML", reply_markup=kb.as_markup()
    )


@router.callback_query(F.data == "a:addproduct")
async def addproduct_start(cq: CallbackQuery, db):
    if not is_admin(cq.from_user.id):
        return
    await cq.answer()
    await choose_product_category(cq, db, None)


@router.callback_query(F.data.startswith("a:addprodcat:"))
async def addproduct_choose_sub(cq: CallbackQuery, db):
    if not is_admin(cq.from_user.id):
        return
    cid = cq.data.split(":", 2)[2]
    subs = await db.subcategories.find({"category_id": oid(cid)}).sort("order", 1).to_list(None)
    kb = InlineKeyboardBuilder()
    for s in subs:
        kb.row(
            b(s["name"], f"a:addproductsub:{s['_id']}", "subcategory",
              s.get("emoji_id"), s.get("button_style", "primary"))
        )
    kb.row(b("Add Sub-category", f"a:addsubcat:{cid}", "add", style="success"))
    kb.row(b("Back", "adm:products", "back", style="danger"))
    await cq.message.edit_text(
        f"{tag('subcategory')} <b>Choose Sub-category</b>",
        parse_mode="HTML", reply_markup=kb.as_markup()
    )


@router.callback_query(F.data.startswith("a:addproductsub:"))
async def addproduct_start(cq: CallbackQuery, state: FSMContext, db):
    if not is_admin(cq.from_user.id):
        return
    sid = cq.data.split(":", 2)[2]
    sub = await db.subcategories.find_one({"_id": oid(sid)})
    if not sub:
        return await cq.answer("Sub-category not found.", show_alert=True)
    await cq.answer()
    await set_prompt_from_callback(
        cq, state, A.addproduct_name,
        f"{tag('products')} <b>Add Product</b>\n\n"
        "1️⃣ Send the product name.",
        f"admprodsub:{sid}",
    )
    await state.update_data(
        sub_id=sid,
        category_id=str(sub["category_id"]),
    )


@router.message(A.addproduct_name)
async def addproduct_name(message: Message, state: FSMContext, bot):
    await delete_user_message(message)
    name = (message.text or "").strip()
    if not name:
        return await edit_prompt(
            bot, message.chat.id, state,
            f"{tag('products')} <b>Add Product</b>\n\n❌ Send a valid name.",
            nav_kb((await state.get_data()).get("flow_back", "adm:products")),
        )
    await state.update_data(name=name)
    await state.set_state(A.addproduct_emoji)
    await edit_prompt(
        bot, message.chat.id, state,
        f"{tag('products')} <b>Add Product</b>\n\n"
        f"Product: <b>{escape(name)}</b>\n\n"
        "2️⃣ Send one premium custom emoji for the product button.",
        nav_kb((await state.get_data()).get("flow_back", "adm:products")),
    )


@router.message(A.addproduct_emoji)
async def addproduct_emoji(message: Message, state: FSMContext, bot):
    eid = custom_emoji_from_message(message)
    await delete_user_message(message)
    if not eid:
        return await edit_prompt(
            bot, message.chat.id, state,
            f"{tag('products')} <b>Add Product</b>\n\n"
            "❌ Send a premium/custom emoji.",
            nav_kb((await state.get_data()).get("flow_back", "adm:products")),
        )
    await state.update_data(emoji_id=eid)
    await state.set_state(A.addproduct_style)
    await edit_prompt(
        bot, message.chat.id, state,
        f"{tag('products')} <b>Add Product</b>\n\n"
        f"Emoji: <code>{eid}</code>\n\n"
        "3️⃣ Choose the button color.",
        style_kb("a:addprodstyle", (await state.get_data()).get("flow_back", "adm:products")),
    )


@router.callback_query(F.data.startswith("a:addprodstyle:"))
async def addproduct_style(cq: CallbackQuery, state: FSMContext, bot):
    style = cq.data.rsplit(":", 1)[1]
    if style not in STYLES:
        return await cq.answer("Invalid style.", show_alert=True)
    await state.update_data(button_style=style)
    await state.set_state(A.addproduct_price)
    d = await state.get_data()
    await cq.answer()
    await edit_prompt(
        bot, cq.from_user.id, state,
        f"{tag('products')} <b>Add Product</b>\n\n"
        f"Product: <b>{escape(d['name'])}</b>\n"
        f"Button: <b>{style_name(style)}</b>\n\n"
        "4️⃣ Send the price in INR.",
        nav_kb(d.get("flow_back", "adm:products")),
    )


@router.message(A.addproduct_price)
async def addproduct_price(message: Message, state: FSMContext, bot):
    await delete_user_message(message)
    try:
        value = float((message.text or "").strip())
        if value <= 0:
            raise ValueError
    except Exception:
        return await edit_prompt(
            bot, message.chat.id, state,
            f"{tag('products')} <b>Add Product</b>\n\n"
            "❌ Send a positive price, e.g. <code>99</code>.",
            nav_kb((await state.get_data()).get("flow_back", "adm:products")),
        )
    await state.update_data(price=value)
    await state.set_state(A.addproduct_description)
    await edit_prompt(
        bot, message.chat.id, state,
        f"{tag('products')} <b>Add Product</b>\n\n"
        f"Price: <b>₹{value:.2f}</b>\n\n"
        "5️⃣ Send the product description.\n"
        "Send <code>-</code> for no description.",
        nav_kb((await state.get_data()).get("flow_back", "adm:products")),
    )


@router.message(A.addproduct_description)
async def addproduct_description(message: Message, state: FSMContext, bot):
    await delete_user_message(message)
    raw = (message.text or "").strip()
    if raw == "-":
        desc = ""
    else:
        desc = message_html(message).strip()
        if not desc:
            return await edit_prompt(
                bot, message.chat.id, state,
                f"{tag('products')} <b>Add Product</b>\n\n"
                "❌ Send a description or <code>-</code>.",
                nav_kb((await state.get_data()).get("flow_back", "adm:products")),
            )
    await state.update_data(description=desc, description_html=desc)
    await state.set_state(A.addproduct_payload)
    await edit_prompt(
        bot, message.chat.id, state,
        f"{tag('stock')} <b>Product Delivery Item</b>\n\n"
        "6️⃣ Send what the buyer should receive:\n"
        "• an <b>https/http link</b>\n"
        "• a document/file\n"
        "• a photo, video, audio or animation\n\n"
        "This exact item will be delivered after purchase.",
        nav_kb((await state.get_data()).get("flow_back", "adm:products")),
    )


@router.message(A.addproduct_payload)
async def addproduct_payload(message: Message, state: FSMContext, bot):
    payload_type = None
    payload = None

    if message.text and message.text.strip().lower().startswith(("http://", "https://")):
        payload_type, payload = "link", message.text.strip()
    elif message.document:
        payload_type, payload = "document", message.document.file_id
    elif message.photo:
        payload_type, payload = "photo", message.photo[-1].file_id
    elif message.video:
        payload_type, payload = "video", message.video.file_id
    elif message.audio:
        payload_type, payload = "audio", message.audio.file_id
    elif message.animation:
        payload_type, payload = "animation", message.animation.file_id

    await delete_user_message(message)

    if not payload:
        return await edit_prompt(
            bot, message.chat.id, state,
            f"{tag('stock')} <b>Product Delivery Item</b>\n\n"
            "❌ Send a valid https/http link or a Telegram file/media.",
            nav_kb((await state.get_data()).get("flow_back", "adm:products")),
        )

    await state.update_data(
        stock_payload_type=payload_type,
        stock_payload=payload,
    )
    await state.set_state(A.addproduct_stock)

    kb = InlineKeyboardBuilder()
    kb.row(b("♾ Unlimited", "a:addstock:unlimited", "confirm", style="success"))
    kb.row(b("1️⃣ Single", "a:addstock:single", "stock", style="primary"))
    kb.row(b("❌ Cancel", "adm:panel", "cancel", style="danger"))
    await edit_prompt(
        bot, message.chat.id, state,
        f"{tag('stock')} <b>Stock Type</b>\n\n"
        "7️⃣ How should this item be sold?\n\n"
        "♾ <b>Unlimited</b> — the same item is delivered to every buyer.\n"
        "1️⃣ <b>Single</b> — this item can be sold once.",
        kb.as_markup(),
    )


@router.callback_query(F.data.startswith("a:addstock:"))
async def addproduct_stock(cq: CallbackQuery, state: FSMContext, db, bot):
    mode = cq.data.rsplit(":", 1)[1]
    if mode not in ("unlimited", "single"):
        return await cq.answer("Invalid stock mode.", show_alert=True)
    d = await state.get_data()
    if not d.get("name") or not d.get("stock_payload"):
        await state.clear()
        return await cq.answer("Product draft expired. Start again.", show_alert=True)

    stock = None if mode == "unlimited" else 1
    await db.products.insert_one({
        "name": d["name"],
        "emoji_id": d["emoji_id"],
        "button_style": d.get("button_style", "primary"),
        "price": float(d["price"]),
        "description": d.get("description", ""),
        "description_html": d.get("description_html", d.get("description", "")),
        "category_id": oid(d["category_id"]),
        "subcategory_id": oid(d["sub_id"]),
        "stock": stock,
        "stock_mode": mode,
        "stock_payload_type": d["stock_payload_type"],
        "stock_payload": d["stock_payload"],
        "active": True,
        "order": 0,
        "created_at": datetime.now(timezone.utc),
    })
    await cq.answer("Product created.")
    await finish_flow(
        bot, cq.from_user.id, state,
        f"✅ <b>Product created</b>\n\n"
        f"{tag('products')} <b>{escape(d['name'])}</b>\n"
        f"💰 ₹{float(d['price']):.2f}\n"
        f"📦 Stock: <b>{'Unlimited' if mode == 'unlimited' else '1'}</b>",
        d.get("flow_back", "adm:products"),
    )


@router.message(Command("addproduct"))
async def addproduct_command(message: Message, db, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    # Use a normal message prompt because there is no callback message yet.
    cats = await db.categories.find({}).sort("order", 1).to_list(None)
    kb = InlineKeyboardBuilder()
    for c in cats:
        kb.row(b(c["name"], f"a:addprodcat:{c['_id']}", "category",
                 c.get("emoji_id"), c.get("button_style", "primary")))
    kb.row(b("◀️ Back", "adm:products", "back", style="danger"))
    msg = await message.answer(
        f"{tag('category')} <b>Choose Category</b>",
        parse_mode="HTML", reply_markup=kb.as_markup()
    )
    await state.clear()
    await state.update_data(prompt_message_id=msg.message_id, flow_back="adm:products")


# ---------- product edit helpers ----------

async def product_edit_start(cq: CallbackQuery, state: FSMContext, db,
                             next_state: State, title: str, pid: str,
                             back: str):
    p = await db.products.find_one({"_id": oid(pid)}) if oid(pid) else None
    if not p:
        return await cq.answer("Product not found.", show_alert=True)
    await cq.answer()
    await state.clear()
    await state.update_data(
        product_id=pid,
        prompt_message_id=cq.message.message_id,
        flow_back=back,
    )
    await state.set_state(next_state)
    await cq.message.edit_text(
        title, parse_mode="HTML", reply_markup=nav_kb(back)
    )


@router.callback_query(F.data.startswith("a:editprodname:"))
async def editprodname(cq, state, db):
    pid = cq.data.rsplit(":", 1)[1]
    p = await db.products.find_one({"_id": oid(pid)}) if oid(pid) else None
    if not p: return await cq.answer("Not found.", show_alert=True)
    await product_edit_start(
        cq, state, db, A.editproduct_name,
        f"✏️ <b>Rename Product</b>\n\nCurrent: <b>{escape(p['name'])}</b>\n\n"
        "Send the new name.", pid, f"admprod:{pid}"
    )


@router.message(A.editproduct_name)
async def editprodname_msg(m, state, db, bot):
    await delete_user_message(m)
    name = (m.text or "").strip()
    d = await state.get_data()
    if not name:
        return await edit_prompt(bot, m.chat.id, state,
                                 "✏️ <b>Rename Product</b>\n\n❌ Invalid name.",
                                 nav_kb(d.get("flow_back", "adm:panel")))
    await db.products.update_one({"_id": oid(d["product_id"])}, {"$set": {"name": name}})
    await finish_flow(bot, m.chat.id, state, "✅ <b>Product name updated.</b>",
                      d.get("flow_back", "adm:panel"))


@router.callback_query(F.data.startswith("a:editprodemoji:"))
async def editprodemoji(cq, state, db):
    pid = cq.data.rsplit(":", 1)[1]
    p = await db.products.find_one({"_id": oid(pid)}) if oid(pid) else None
    if not p: return await cq.answer("Not found.", show_alert=True)
    await product_edit_start(
        cq, state, db, A.editproduct_emoji,
        "🎨 <b>Change Product Emoji</b>\n\nSend the new premium custom emoji.",
        pid, f"admprod:{pid}"
    )


@router.message(A.editproduct_emoji)
async def editprodemoji_msg(m, state, db, bot):
    eid = custom_emoji_from_message(m)
    await delete_user_message(m)
    d = await state.get_data()
    if not eid:
        return await edit_prompt(bot, m.chat.id, state,
                                 "🎨 <b>Change Product Emoji</b>\n\n"
                                 "❌ Send a premium/custom emoji.",
                                 nav_kb(d.get("flow_back", "adm:panel")))
    await db.products.update_one({"_id": oid(d["product_id"])}, {"$set": {"emoji_id": eid}})
    await finish_flow(bot, m.chat.id, state, "✅ <b>Product emoji updated.</b>",
                      d.get("flow_back", "adm:panel"))


@router.callback_query(F.data.startswith("a:editprodstyle:"))
async def editprodstyle(cq, state, db):
    pid = cq.data.rsplit(":", 1)[1]
    p = await db.products.find_one({"_id": oid(pid)}) if oid(pid) else None
    if not p: return await cq.answer("Not found.", show_alert=True)
    await state.clear()
    await state.update_data(product_id=pid, prompt_message_id=cq.message.message_id,
                            flow_back=f"admprod:{pid}")
    await state.set_state(A.editproduct_style)
    await cq.message.edit_text(
        "🎨 <b>Change Product Button Color</b>\n\nChoose the new color.",
        parse_mode="HTML", reply_markup=style_kb("a:editprodstylevalue", f"admprod:{pid}")
    )


@router.callback_query(F.data.startswith("a:editprodstylevalue:"))
async def editprodstylevalue(cq, state, db, bot):
    style = cq.data.rsplit(":", 1)[1]
    d = await state.get_data()
    await db.products.update_one({"_id": oid(d["product_id"])},
                                 {"$set": {"button_style": style}})
    await cq.answer("Button color updated.")
    await finish_flow(bot, cq.from_user.id, state,
                      "✅ <b>Product button color updated.</b>",
                      d.get("flow_back", "adm:panel"))


@router.callback_query(F.data.startswith("a:editprodprice:"))
async def editprodprice(cq, state, db):
    pid = cq.data.rsplit(":", 1)[1]
    p = await db.products.find_one({"_id": oid(pid)}) if oid(pid) else None
    if not p: return await cq.answer("Not found.", show_alert=True)
    await product_edit_start(
        cq, state, db, A.editproduct_price,
        f"💰 <b>Change Price</b>\n\nCurrent: ₹{float(p['price']):.2f}\n\n"
        "Send the new price.", pid, f"admprod:{pid}"
    )


@router.message(A.editproduct_price)
async def editprodprice_msg(m, state, db, bot):
    await delete_user_message(m)
    try:
        v = float((m.text or "").strip())
        if v <= 0: raise ValueError
    except Exception:
        return await edit_prompt(bot, m.chat.id, state,
                                 "💰 <b>Change Price</b>\n\n❌ Enter a positive number.",
                                 nav_kb((await state.get_data()).get("flow_back", "adm:panel")))
    d = await state.get_data()
    await db.products.update_one({"_id": oid(d["product_id"])}, {"$set": {"price": v}})
    await finish_flow(bot, m.chat.id, state, "✅ <b>Product price updated.</b>",
                      d.get("flow_back", "adm:panel"))


@router.callback_query(F.data.startswith("a:editproddesc:"))
async def editproddesc(cq, state, db):
    pid = cq.data.rsplit(":", 1)[1]
    await product_edit_start(
        cq, state, db, A.editproduct_description,
        "📝 <b>Change Description</b>\n\n"
        "Send the new description or <code>-</code>.\n\n"
        "Premium/custom emojis in your message will be preserved.",
        pid, f"admprod:{pid}"
    )


@router.message(A.editproduct_description)
async def editproddesc_msg(m, state, db, bot):
    await delete_user_message(m)
    raw = (m.text or "").strip()
    d = await state.get_data()
    desc = "" if raw == "-" else message_html(m).strip()
    if raw != "-" and not desc:
        return await edit_prompt(bot, m.chat.id, state,
                                 "📝 <b>Change Description</b>\n\n"
                                 "❌ Send a description or <code>-</code>.",
                                 nav_kb(d.get("flow_back", "adm:panel")))
    await db.products.update_one(
        {"_id": oid(d["product_id"])},
        {"$set": {"description": desc, "description_html": desc}},
    )
    await finish_flow(bot, m.chat.id, state, "✅ <b>Description updated.</b>",
                      d.get("flow_back", "adm:panel"))


@router.callback_query(F.data.startswith("a:editprodstock:"))
async def editprodstock(cq, state, db):
    pid = cq.data.rsplit(":", 1)[1]
    await product_edit_start(
        cq, state, db, A.editproduct_stock,
        "📦 <b>Change Stock</b>\n\n"
        "Choose how this product should be sold.",
        pid, f"admprod:{pid}"
    )
    # Replace the text keyboard with explicit stock choices.
    kb = InlineKeyboardBuilder()
    kb.row(b("♾ Unlimited", "a:editstockmode:unlimited", "confirm", style="success"))
    kb.row(b("1️⃣ Single", "a:editstockmode:single", "stock", style="primary"))
    kb.row(b("◀️ Back", f"admprod:{pid}", "back", style="danger"))
    await cq.message.edit_text(
        "📦 <b>Change Stock</b>\n\nChoose stock mode.",
        parse_mode="HTML", reply_markup=kb.as_markup()
    )


@router.callback_query(F.data.startswith("a:editstockmode:"))
async def editstockmode(cq, state, db, bot):
    mode = cq.data.rsplit(":", 1)[1]
    if mode not in ("unlimited", "single"):
        return await cq.answer("Invalid stock mode.", show_alert=True)
    d = await state.get_data()
    await db.products.update_one(
        {"_id": oid(d["product_id"])},
        {"$set": {
            "stock": None if mode == "unlimited" else 1,
            "stock_mode": mode,
        }},
    )
    await cq.answer("Stock updated.")
    await finish_flow(bot, cq.from_user.id, state,
                      f"✅ <b>Stock updated</b>\n\nMode: <b>{mode.title()}</b>",
                      d.get("flow_back", "adm:panel"))


@router.callback_query(F.data.startswith("a:editprodpayload:"))
async def editprodpayload(cq, state, db):
    pid = cq.data.rsplit(":", 1)[1]
    await product_edit_start(
        cq, state, db, A.editproduct_payload,
        "🔗 <b>Change Delivery Item</b>\n\n"
        "Send a new https/http link or Telegram file/media.",
        pid, f"admprod:{pid}"
    )


@router.message(A.editproduct_payload)
async def editprodpayload_msg(m, state, db, bot):
    payload_type = None
    payload = None
    if m.text and m.text.strip().lower().startswith(("http://", "https://")):
        payload_type, payload = "link", m.text.strip()
    elif m.document:
        payload_type, payload = "document", m.document.file_id
    elif m.photo:
        payload_type, payload = "photo", m.photo[-1].file_id
    elif m.video:
        payload_type, payload = "video", m.video.file_id
    elif m.audio:
        payload_type, payload = "audio", m.audio.file_id
    elif m.animation:
        payload_type, payload = "animation", m.animation.file_id
    await delete_user_message(m)
    d = await state.get_data()
    if not payload:
        return await edit_prompt(bot, m.chat.id, state,
                                 "🔗 <b>Change Delivery Item</b>\n\n"
                                 "❌ Send a valid link or Telegram file/media.",
                                 nav_kb(d.get("flow_back", "adm:panel")))
    await db.products.update_one(
        {"_id": oid(d["product_id"])},
        {"$set": {
            "stock_payload_type": payload_type,
            "stock_payload": payload,
        }},
    )
    await finish_flow(bot, m.chat.id, state, "✅ <b>Delivery item updated.</b>",
                      d.get("flow_back", "adm:panel"))


@router.callback_query(F.data.startswith("a:delprod:"))
async def delprod_confirm(cq, db):
    pid = oid(cq.data.rsplit(":", 1)[1])
    p = await db.products.find_one({"_id": pid}) if pid else None
    if not p:
        return await cq.answer("Not found.", show_alert=True)
    kb = InlineKeyboardBuilder()
    kb.row(b("🗑️ Yes, Delete", f"a:delprod_yes:{pid}", "delete", style="danger"))
    kb.row(b("Cancel", f"admprod:{pid}", "cancel", style="primary"))
    await cq.message.edit_text(
        f"⚠️ <b>Delete {escape(p['name'])}?</b>\n\n"
        "This cannot be undone.",
        parse_mode="HTML", reply_markup=kb.as_markup()
    )


@router.callback_query(F.data.startswith("a:delprod_yes:"))
async def delprod(cq, db):
    pid = oid(cq.data.rsplit(":", 1)[1])
    p = await db.products.find_one({"_id": pid}) if pid else None
    if p:
        await db.products.delete_one({"_id": pid})
    await cq.answer("Deleted.")
    if p:
        # Return to the sub-category that contained it.
        fake = cq.message
        await fake.edit_text("🛍️ <b>Product deleted.</b>",
                              parse_mode="HTML",
                              reply_markup=simple_back("adm:products"))


# ============================================================
# STOCK MANAGEMENT
# ============================================================

@router.callback_query(F.data == "adm:stock")
async def stock_panel(cq: CallbackQuery, db, state: FSMContext):
    if not is_admin(cq.from_user.id):
        return
    await state.clear()
    cats = await db.categories.find({}).sort("order", 1).to_list(None)
    kb = InlineKeyboardBuilder()
    for c in cats:
        kb.row(b(c["name"], f"admstockcat:{c['_id']}", "category",
                 c.get("emoji_id"), c.get("button_style", "primary")))
    kb.row(b("◀️ Back", "adm:panel", "back", style="danger"))
    await cq.answer()
    await cq.message.edit_text(
        f"{tag('stock')} <b>Stock Management</b>\n\nChoose a category.",
        parse_mode="HTML", reply_markup=kb.as_markup()
    )


@router.callback_query(F.data.startswith("admstockcat:"))
async def stock_cat(cq: CallbackQuery, db, state: FSMContext):
    cid = oid(cq.data.split(":", 1)[1])
    xs = await db.subcategories.find({"category_id": cid}).sort("order", 1).to_list(None)
    kb = InlineKeyboardBuilder()
    for s in xs:
        kb.row(b(s["name"], f"admstocksub:{s['_id']}", "subcategory",
                 s.get("emoji_id"), s.get("button_style", "primary")))
    kb.row(b("◀️ Back", "adm:stock", "back", style="danger"))
    await cq.message.edit_text(
        f"{tag('subcategory')} <b>Choose Sub-category</b>",
        parse_mode="HTML", reply_markup=kb.as_markup()
    )


@router.callback_query(F.data.startswith("admstocksub:"))
async def stock_sub(cq: CallbackQuery, db, state: FSMContext):
    sid = oid(cq.data.split(":", 1)[1])
    xs = await db.products.find({"subcategory_id": sid}).sort("order", 1).to_list(None)
    kb = InlineKeyboardBuilder()
    for p in xs:
        stock = "∞" if p.get("stock") is None else str(p.get("stock", 0))
        kb.row(b(f"{p['name']} · {stock}", f"admprod:{p['_id']}", "stock",
                 p.get("emoji_id"), p.get("button_style", "primary")))
    kb.row(b("◀️ Back", "adm:stock", "back", style="danger"))
    await cq.message.edit_text(
        f"{tag('stock')} <b>Choose Product</b>\n\n"
        "Unlimited = ∞",
        parse_mode="HTML", reply_markup=kb.as_markup()
    )


@router.message(Command("stock"))
async def stock_cmd(message: Message):
    if is_admin(message.from_user.id):
        await message.answer(
            f"{tag('stock')} <b>Stock Management</b>\n\n"
            "Open /admin → Stock.",
            parse_mode="HTML", reply_markup=panel_kb()
        )


# ============================================================
# ORDERS
# ============================================================

@router.callback_query(F.data == "adm:orders")
async def orders(cq: CallbackQuery, db, state: FSMContext):
    if not is_admin(cq.from_user.id):
        return
    await state.clear()
    xs = await db.orders.find({}).sort("created_at", -1).limit(30).to_list(None)
    if not xs:
        text = f"{tag('orders')} <b>Orders</b>\n\nNo orders yet."
    else:
        lines = []
        for x in xs:
            total = float(x.get("total", 0))
            lines.append(
                f"• <b>{escape(str(x.get('product_name','Product')))}</b> × "
                f"{x.get('quantity',1)} — ₹{total:.2f}"
            )
        text = f"{tag('orders')} <b>Recent Orders</b>\n\n" + "\n".join(lines)
    await cq.answer()
    await cq.message.edit_text(text, parse_mode="HTML", reply_markup=simple_back())


# ============================================================
# USERS
# ============================================================

def users_kb() -> Any:
    kb = InlineKeyboardBuilder()
    kb.row(b("🔎 Find User", "a:userlookup", "search"))
    kb.row(
        b("➕ Add Balance", "a:addbalance", "money", style="success"),
        b("💰 Set Balance", "a:setbalance", "money"),
        b("➖ Debit Balance", "a:debitbalance", "money", style="danger"),
    )
    kb.row(
        b("🔒 Ban User", "a:ban", "danger", style="danger"),
        b("🔓 Unban User", "a:unban", "confirm"),
    )
    kb.row(b("◀️ Back", "adm:panel", "back", style="danger"))
    return kb.as_markup()


async def resolve_user(db, query: str):
    q = query.strip()
    if q.lstrip("@").isdigit():
        return await db.users.find_one({"telegram_id": int(q.lstrip("@"))})
    return await db.users.find_one({"username": q.lstrip("@")})


@router.callback_query(F.data == "adm:users")
async def users(cq: CallbackQuery, db, state: FSMContext):
    if not is_admin(cq.from_user.id):
        return
    await state.clear()
    n = await db.users.count_documents({})
    await cq.answer()
    await cq.message.edit_text(
        f"{tag('profile')} <b>Users</b>\n\n"
        f"Registered users: <b>{n}</b>\n\n"
        "Choose an action.",
        parse_mode="HTML", reply_markup=users_kb()
    )


@router.callback_query(F.data == "a:userlookup")
async def userlookup(cq, state):
    await cq.answer()
    await set_prompt_from_callback(
        cq, state, A.user_lookup,
        f"{tag('profile')} <b>Find User</b>\n\n"
        "Send Telegram ID or @username.",
        "adm:users",
    )


@router.message(A.user_lookup)
async def userlookup_msg(m, state, db, bot):
    await delete_user_message(m)
    u = await resolve_user(db, m.text or "")
    d = await state.get_data()
    if not u:
        return await edit_prompt(
            bot, m.chat.id, state,
            f"{tag('profile')} <b>Find User</b>\n\n"
            "❌ User not found.\n\nSend another ID or @username.",
            nav_kb("adm:users"),
        )
    await state.clear()
    text = (
        f"{tag('profile')} <b>User</b>\n\n"
        f"Name: <b>{escape(u.get('full_name','User'))}</b>\n"
        f"ID: <code>{u.get('telegram_id')}</code>\n"
        f"Username: @{escape(u.get('username') or 'N/A')}\n"
        f"Balance: <b>₹{float(u.get('balance',0)):.2f}</b>\n"
        f"Referrals: <b>{int(u.get('referrals',0))}</b>\n"
        f"Banned: <b>{'Yes' if u.get('banned') else 'No'}</b>"
    )
    kb = InlineKeyboardBuilder()
    kb.row(b("◀️ Back", "adm:users", "back", style="danger"))
    await bot.edit_message_text(chat_id=m.chat.id, message_id=d.get("prompt_message_id"),
                                 text=text, parse_mode="HTML", reply_markup=kb.as_markup())


@router.callback_query(F.data == "a:addbalance")
async def addbalance_start(cq, state):
    await cq.answer()
    await set_prompt_from_callback(
        cq, state, A.addbalance_user,
        f"{tag('money')} <b>Add Balance</b>\n\n"
        "Send Telegram ID or @username.",
        "adm:users",
    )


@router.message(A.addbalance_user)
async def addbalance_user(m, state, db, bot):
    await delete_user_message(m)
    u = await resolve_user(db, m.text or "")
    d = await state.get_data()
    if not u:
        return await edit_prompt(bot, m.chat.id, state,
                                 "💰 <b>Add Balance</b>\n\n"
                                 "❌ User not found.",
                                 nav_kb("adm:users"))
    await state.update_data(target=u["telegram_id"], target_name=u.get("full_name", "User"))
    await state.set_state(A.addbalance_amount)
    await edit_prompt(
        bot, m.chat.id, state,
        f"💰 <b>Add Balance</b>\n\n"
        f"User: <b>{escape(u.get('full_name','User'))}</b>\n"
        f"Current: <b>₹{float(u.get('balance',0)):.2f}</b>\n\n"
        "Send the amount to add.",
        nav_kb("adm:users"),
    )


@router.message(A.addbalance_amount)
async def addbalance_amount(m, state, db, bot):
    await delete_user_message(m)
    try:
        amount = float((m.text or "").strip())
        if amount <= 0: raise ValueError
    except Exception:
        return await edit_prompt(bot, m.chat.id, state,
                                 "💰 <b>Add Balance</b>\n\n❌ Enter a positive amount.",
                                 nav_kb("adm:users"))
    d = await state.get_data()
    try:
        u = await record_balance_change(
            db, user_id=d["target"], admin_id=m.from_user.id, delta=amount,
            action="credit", reason="Admin panel credit"
        )
    except ValueError:
        return await finish_flow(bot, m.chat.id, state, "❌ <b>Balance update failed.</b>", "adm:users")
    await log_audit(db, bot, admin_id=m.from_user.id, action="CREDIT", target_id=d["target"], details=f"+₹{amount:.2f}")
    await finish_flow(
        bot, m.chat.id, state,
        f"✅ <b>Balance added</b>\n\n"
        f"User: <b>{escape(d.get('target_name','User'))}</b>\n"
        f"Added: <b>₹{amount:.2f}</b>\n"
        f"New balance: <b>₹{float((u or {}).get('balance',0)):.2f}</b>",
        "adm:users",
    )


@router.callback_query(F.data == "a:setbalance")
async def setbalance_start(cq, state):
    await cq.answer()
    await set_prompt_from_callback(
        cq, state, A.setbalance_user,
        "💰 <b>Set Balance</b>\n\nSend Telegram ID or @username.",
        "adm:users",
    )


@router.message(A.setbalance_user)
async def setbalance_user(m, state, db, bot):
    await delete_user_message(m)
    u = await resolve_user(db, m.text or "")
    if not u:
        return await edit_prompt(bot, m.chat.id, state,
                                 "💰 <b>Set Balance</b>\n\n❌ User not found.",
                                 nav_kb("adm:users"))
    await state.update_data(target=u["telegram_id"], target_name=u.get("full_name", "User"))
    await state.set_state(A.setbalance_amount)
    await edit_prompt(
        bot, m.chat.id, state,
        f"💰 <b>Set Balance</b>\n\n"
        f"User: <b>{escape(u.get('full_name','User'))}</b>\n"
        f"Current: <b>₹{float(u.get('balance',0)):.2f}</b>\n\n"
        "Send the new balance.",
        nav_kb("adm:users"),
    )


@router.message(A.setbalance_amount)
async def setbalance_amount(m, state, db, bot):
    await delete_user_message(m)
    try:
        value = float((m.text or "").strip())
        if value < 0: raise ValueError
    except Exception:
        return await edit_prompt(bot, m.chat.id, state,
                                 "💰 <b>Set Balance</b>\n\n❌ Enter 0 or a positive amount.",
                                 nav_kb("adm:users"))
    d = await state.get_data()
    u = await db.users.find_one({"telegram_id": d["target"]})
    old_value = float((u or {}).get("balance", 0))
    await db.users.update_one(
        {"telegram_id": d["target"]},
        {"$set": {"balance": value}},
    )
    delta = round(value - old_value, 2)
    await db.balance_ledger.insert_one({"user_id": d["target"], "admin_id": m.from_user.id, "delta": delta, "action": "set", "reason": "Admin panel set balance", "balance_after": value, "created_at": datetime.now(timezone.utc)})
    await log_audit(db, bot, admin_id=m.from_user.id, action="SET_BALANCE", target_id=d["target"], details=f"₹{old_value:.2f} → ₹{value:.2f}")
    await finish_flow(
        bot, m.chat.id, state,
        f"✅ <b>Balance updated</b>\n\n"
        f"New balance: <b>₹{value:.2f}</b>",
        "adm:users",
    )


@router.callback_query(F.data == "a:debitbalance")
async def debitbalance_start(cq, state):
    if not is_admin(cq.from_user.id): return
    await cq.answer()
    await set_prompt_from_callback(cq, state, A.debitbalance_user,
        f"{tag('money')} <b>Debit Balance</b>\n\nSend Telegram ID or @username.", "adm:users")

@router.message(A.debitbalance_user)
async def debitbalance_user(m, state, db, bot):
    await delete_user_message(m)
    u = await resolve_user(db, m.text or "")
    if not u:
        return await edit_prompt(bot, m.chat.id, state, "➖ <b>Debit Balance</b>\n\n❌ User not found.", nav_kb("adm:users"))
    await state.update_data(target=u["telegram_id"], target_name=u.get("full_name", "User"), current_balance=float(u.get("balance", 0)))
    await state.set_state(A.debitbalance_amount)
    await edit_prompt(bot, m.chat.id, state, f"➖ <b>Debit Balance</b>\n\nUser: <b>{escape(u.get('full_name','User'))}</b>\nCurrent: <b>₹{float(u.get('balance',0)):.2f}</b>\n\nSend amount to debit.", nav_kb("adm:users"))

@router.message(A.debitbalance_amount)
async def debitbalance_amount(m, state, db, bot):
    await delete_user_message(m)
    try:
        amount=float((m.text or '').strip())
        if amount <= 0: raise ValueError
    except Exception:
        return await edit_prompt(bot, m.chat.id, state, "➖ <b>Debit Balance</b>\n\n❌ Enter a positive amount.", nav_kb("adm:users"))
    d=await state.get_data()
    try:
        u=await record_balance_change(db, user_id=d['target'], admin_id=m.from_user.id, delta=-amount, action='debit', reason='Admin panel debit')
    except ValueError:
        return await finish_flow(bot, m.chat.id, state, "❌ <b>Debit failed.</b>\n\nUser does not have enough balance.", "adm:users")
    await log_audit(db, bot, admin_id=m.from_user.id, action='DEBIT', target_id=d['target'], details=f"-₹{amount:.2f}")
    await finish_flow(bot, m.chat.id, state, f"✅ <b>Balance debited</b>\n\nUser: <b>{escape(d.get('target_name','User'))}</b>\nDebited: <b>₹{amount:.2f}</b>\nNew balance: <b>₹{float(u.get('balance',0)):.2f}</b>", "adm:users")


@router.callback_query(F.data == "a:ban")
async def ban_start(cq, state):
    await cq.answer()
    await set_prompt_from_callback(
        cq, state, A.ban_user,
        "🔒 <b>Ban User</b>\n\nSend Telegram ID or @username.",
        "adm:users",
    )


@router.message(A.ban_user)
async def ban_user(m, state, db, bot):
    await delete_user_message(m)
    u = await resolve_user(db, m.text or "")
    if not u:
        return await edit_prompt(bot, m.chat.id, state,
                                 "🔒 <b>Ban User</b>\n\n❌ User not found.",
                                 nav_kb("adm:users"))
    await db.users.update_one({"telegram_id": u["telegram_id"]}, {"$set": {"banned": True}})
    await finish_flow(bot, m.chat.id, state, "✅ <b>User banned.</b>", "adm:users")


@router.callback_query(F.data == "a:unban")
async def unban_start(cq, state):
    await cq.answer()
    await set_prompt_from_callback(
        cq, state, A.unban_user,
        "🔓 <b>Unban User</b>\n\nSend Telegram ID or @username.",
        "adm:users",
    )


@router.message(A.unban_user)
async def unban_user(m, state, db, bot):
    await delete_user_message(m)
    u = await resolve_user(db, m.text or "")
    if not u:
        return await edit_prompt(bot, m.chat.id, state,
                                 "🔓 <b>Unban User</b>\n\n❌ User not found.",
                                 nav_kb("adm:users"))
    await db.users.update_one({"telegram_id": u["telegram_id"]}, {"$set": {"banned": False}})
    await finish_flow(bot, m.chat.id, state, "✅ <b>User unbanned.</b>", "adm:users")


# ============================================================
# BROADCAST
# ============================================================

async def _broadcast_source(source: Message, db, bot, admin_id: int):
    """Copy a message to every eligible user.

    copy_to() is intentional: it removes Telegram's forwarded-from header
    while preserving the original message content/entities, including
    Telegram custom/premium emoji entities.
    """
    users = await db.users.find(
        {"banned": {"$ne": True}, "telegram_id": {"$exists": True}},
        {"telegram_id": 1},
    ).to_list(None)

    sent = failed = 0
    for u in users:
        uid = u.get("telegram_id")
        if not uid:
            continue
        try:
            await source.copy_to(chat_id=uid)
            sent += 1
        except Exception:
            failed += 1

    await db.broadcasts.insert_one({
        "admin_id": admin_id,
        "source_chat_id": source.chat.id,
        "source_message_id": source.message_id,
        "sent": sent,
        "failed": failed,
        "created_at": datetime.now(timezone.utc),
    })
    return sent, failed


@router.callback_query(F.data == "adm:broadcast")
async def broadcast_start(cq, state):
    if not is_admin(cq.from_user.id):
        return
    await cq.answer()
    await set_prompt_from_callback(
        cq, state, A.broadcast,
        f"{tag('broadcast')} <b>Broadcast</b>\n\n"
        "Reply to any message with <code>/broadcast</code> to send it "
        "to every eligible user.\n\n"
        "Or tap this button and then send a message/photo/video.\n\n"
        "Premium/custom emoji will remain intact and Telegram's forwarded "
        "header will not be added.",
        "adm:panel",
    )


@router.message(Command("broadcast"))
async def broadcast_command(m, state, db, bot):
    if not is_admin(m.from_user.id):
        return

    # Fast mode: /broadcast is a reply to the exact message to send.
    if m.reply_to_message:
        await delete_user_message(m)
        status = await m.answer(
            f"{tag('broadcast')} <b>Broadcasting…</b>\n\n"
            "Please wait while the message is copied to all users.",
            parse_mode="HTML",
        )
        sent, failed = await _broadcast_source(
            m.reply_to_message, db, bot, m.from_user.id
        )
        try:
            await status.edit_text(
                f"{tag('broadcast')} <b>Broadcast complete</b>\n\n"
                f"Sent: <b>{sent}</b>\n"
                f"Failed: <b>{failed}</b>",
                parse_mode="HTML",
                reply_markup=panel_kb(),
            )
        except Exception:
            pass
        return

    # Normal mode: /broadcast opens a prompt for the next message.
    await start_flow_from_message(
        m, state, A.broadcast,
        f"{tag('broadcast')} <b>Broadcast</b>\n\n"
        "Send the message/photo/video to broadcast.\n\n"
        "Tip: you can also reply to any message with <code>/broadcast</code>.",
        "adm:panel",
    )


@router.message(A.broadcast)
async def broadcast_message(m, state, db, bot):
    if not is_admin(m.from_user.id):
        return

    # IMPORTANT: broadcast BEFORE deleting the source message.
    # The previous version deleted m first and then tried m.copy_to(),
    # which guaranteed failures and produced Sent: 0.
    sent, failed = await _broadcast_source(
        m, db, bot, m.from_user.id
    )
    await delete_user_message(m)

    await finish_flow(
        bot, m.chat.id, state,
        f"{tag('broadcast')} <b>Broadcast complete</b>\n\n"
        f"Sent: <b>{sent}</b>\n"
        f"Failed: <b>{failed}</b>",
        "adm:panel",
    )


# ============================================================

# REFERRALS
# ============================================================

async def referral_settings(db):
    s = await db.settings.find_one({"_id": "referrals"})
    if not s:
        s = {
            "_id": "referrals",
            "reward": 1.0,
            "enabled": True,
        }
        await db.settings.insert_one(s)
    return s


@router.callback_query(F.data == "adm:referrals")
async def referral_panel(cq, db, state: FSMContext):
    if not is_admin(cq.from_user.id):
        return
    await state.clear()
    s = await referral_settings(db)
    enabled = "🟢 ON" if s.get("enabled", True) else "🔴 OFF"
    reward = float(s.get("reward", 1.0))
    kb = InlineKeyboardBuilder()
    kb.row(b(f"Reward: ₹{reward:.2f}", "a:refreward", "money", style="success"))
    kb.row(b(f"Referral System: {enabled}", "a:reftoggle", "refer"))
    kb.row(b("◀️ Back", "adm:panel", "back", style="danger"))
    await cq.answer()
    await cq.message.edit_text(
        f"{tag('refer')} <b>Referral Settings</b>\n\n"
        f"Reward per successful referral: <b>₹{reward:.2f}</b>\n"
        f"Status: <b>{enabled}</b>\n\n"
        "The reward is intended to be credited only after the referred user "
        "successfully passes force-join verification.",
        parse_mode="HTML", reply_markup=kb.as_markup()
    )


@router.callback_query(F.data == "a:reftoggle")
async def referral_toggle(cq, db, state: FSMContext):
    if not is_admin(cq.from_user.id):
        return
    s = await referral_settings(db)
    new = not s.get("enabled", True)
    await db.settings.update_one({"_id": "referrals"}, {"$set": {"enabled": new}})
    await cq.answer("Updated.")
    await referral_panel(cq, db, state)


@router.callback_query(F.data == "a:refreward")
async def referral_reward_start(cq, state, db):
    if not is_admin(cq.from_user.id):
        return
    s = await referral_settings(db)
    await cq.answer()
    await state.clear()
    await state.update_data(
        prompt_message_id=cq.message.message_id,
        flow_back="adm:referrals",
    )
    await state.set_state(A.referral_reward)
    await cq.message.edit_text(
        f"{tag('refer')} <b>Referral Reward</b>\n\n"
        f"Current: <b>₹{float(s.get('reward',1.0)):.2f}</b>\n\n"
        "Send the new reward amount.",
        parse_mode="HTML", reply_markup=nav_kb("adm:referrals")
    )


@router.message(A.referral_reward)
async def referral_reward_value(m, state, db, bot):
    await delete_user_message(m)
    try:
        value = float((m.text or "").strip())
        if value < 0: raise ValueError
    except Exception:
        return await edit_prompt(
            bot, m.chat.id, state,
            f"{tag('refer')} <b>Referral Reward</b>\n\n"
            "❌ Enter 0 or a positive amount.",
            nav_kb("adm:referrals"),
        )
    await db.settings.update_one(
        {"_id": "referrals"},
        {"$set": {"reward": value, "enabled": True}},
        upsert=True,
    )
    await finish_flow(
        bot, m.chat.id, state,
        f"✅ <b>Referral reward updated</b>\n\n"
        f"Reward: <b>₹{value:.2f}</b>",
        "adm:referrals",
    )


# ============================================================
# PAYMENTS
# ============================================================

@router.callback_query(F.data == "adm:payments")
async def payment_admin(cq, db, state: FSMContext):
    if not is_admin(cq.from_user.id):
        return
    await state.clear()
    s = await db.settings.find_one({"_id": "payments"}) or {}
    p = "🟢 ON" if s.get("payments_active", True) else "🔴 OFF"
    u = "🟢 ON" if s.get("upi_active", True) else "🔴 OFF"
    c = "🟢 ON" if s.get("usdt_active", True) else "🔴 OFF"
    kb = InlineKeyboardBuilder()
    kb.row(b(f"All Payments: {p}", "fundtoggle:payments_active", "money"))
    kb.row(b(f"UPI: {u}", "fundtoggle:upi_active", "wallet"))
    kb.row(b(f"Crypto: {c}", "fundtoggle:usdt_active", "money"))
    kb.row(b("⚙️ Payment Settings", "paysettings", "edit"))
    kb.row(b("◀️ Back", "adm:panel", "back", style="danger"))
    await cq.answer()
    await cq.message.edit_text(
        f"{tag('money')} <b>Payment Control</b>\n\n"
        "Gateway status and payment configuration.",
        parse_mode="HTML", reply_markup=kb.as_markup()
    )


# ============================================================
# FORCE JOIN
# ============================================================

@router.callback_query(F.data == "adm:forcejoin")
async def forcejoin(cq: CallbackQuery, state: FSMContext):
    if not is_admin(cq.from_user.id):
        return
    await state.clear()
    kb = InlineKeyboardBuilder()
    kb.row(b("Channel 1", "a:fj1", "forcejoin"))
    kb.row(b("Channel 2", "a:fj2", "forcejoin"))
    kb.row(b("◀️ Back", "adm:panel", "back", style="danger"))
    await cq.answer()
    await cq.message.edit_text(
        f"{tag('forcejoin')} <b>Force Join</b>\n\n"
        f"Channel 1: <code>{escape(FORCE_JOIN_1 or 'Not set')}</code>\n"
        f"Channel 2: <code>{escape(FORCE_JOIN_2 or 'Not set')}</code>\n\n"
        "Change FORCE_JOIN_1 / FORCE_JOIN_2 in .env and restart.",
        parse_mode="HTML", reply_markup=kb.as_markup()
    )


@router.callback_query(F.data == "a:fj1")
async def forcejoin_one(cq):
    if is_admin(cq.from_user.id):
        await cq.answer("Edit FORCE_JOIN_1 in .env, then restart.", show_alert=True)


@router.callback_query(F.data == "a:fj2")
async def forcejoin_two(cq):
    if is_admin(cq.from_user.id):
        await cq.answer("Edit FORCE_JOIN_2 in .env, then restart.", show_alert=True)


@router.message(Command("setforcejoin"))
async def setforcejoin_cmd(m):
    if is_admin(m.from_user.id):
        await m.answer(
            f"{tag('forcejoin')} <b>Force Join</b>\n\n"
            "Set FORCE_JOIN_1 and FORCE_JOIN_2 in .env, then restart.",
            parse_mode="HTML", reply_markup=panel_kb()
        )


# ============================================================
# PREMIUM EMOJI
# ============================================================

@router.callback_query(F.data == "adm:emoji")
async def emoji_panel(cq, state: FSMContext):
    if not is_admin(cq.from_user.id):
        return
    await state.clear()
    await cq.answer()
    await cq.message.edit_text(
        f"🎨 <b>Premium Emoji</b>\n\n"
        "Default bot emoji IDs are configured in:\n"
        "<code>utils/premium_emoji.py</code>\n\n"
        "Category, sub-category and product buttons use their own saved "
        "premium custom emoji IDs.\n\n"
        "Descriptions preserve Telegram custom emoji entities when entered "
        "by the admin.",
        parse_mode="HTML", reply_markup=simple_back()
    )


# ============================================================
# STATISTICS
# ============================================================

@router.callback_query(F.data == "adm:stats")
async def stats(cq, db, state: FSMContext):
    if not is_admin(cq.from_user.id):
        return
    await state.clear()
    users = await db.users.count_documents({})
    cats = await db.categories.count_documents({"active": True})
    subs = await db.subcategories.count_documents({"active": True})
    products = await db.products.count_documents({"active": True})
    orders = await db.orders.count_documents({})
    transactions = await db.transactions.count_documents({})
    revenue = 0.0
    async for row in db.orders.aggregate([
        {"$match": {"status": "paid"}},
        {"$group": {"_id": None, "total": {"$sum": "$total"}}},
    ]):
        revenue = float(row.get("total", 0))
    await cq.answer()
    await cq.message.edit_text(
        f"{tag('stats')} <b>Statistics</b>\n\n"
        f"👥 Users: <b>{users}</b>\n"
        f"📂 Categories: <b>{cats}</b>\n"
        f"🗂️ Sub-categories: <b>{subs}</b>\n"
        f"🛍️ Products: <b>{products}</b>\n"
        f"🧾 Orders: <b>{orders}</b>\n"
        f"💳 Transactions: <b>{transactions}</b>\n"
        f"💰 Sales: <b>₹{revenue:.2f}</b>",
        parse_mode="HTML", reply_markup=simple_back()
    )


# ============================================================
# AUDIT / MAINTENANCE
# ============================================================

@router.callback_query(F.data == "adm:audit")
async def audit_panel(cq, db, state):
    if not is_admin(cq.from_user.id): return
    await state.clear(); await cq.answer()
    rows = await db.audit_logs.find({}).sort("created_at", -1).limit(20).to_list(None)
    if not rows:
        text = f"{tag('log')} <b>Audit Logs</b>\n\nNo admin actions recorded yet."
    else:
        lines=[]
        for r in rows:
            lines.append(f"• <b>{escape(str(r.get('action','ACTION')))}</b> · <code>{r.get('admin_id')}</code> → <code>{r.get('target_id') or '—'}</code>\n  {escape(str(r.get('details','')))[:180]}")
        text=f"{tag('log')} <b>Recent Admin Actions</b>\n\n"+'\n'.join(lines)
    await cq.message.edit_text(text, parse_mode='HTML', reply_markup=simple_back())

@router.callback_query(F.data == "adm:maintenance")
async def maintenance_panel(cq, db, state):
    if not is_admin(cq.from_user.id): return
    await state.clear(); s=await db.settings.find_one({'_id':'maintenance'}) or {'enabled':False}
    enabled=bool(s.get('enabled',False))
    kb=InlineKeyboardBuilder()
    kb.row(b('🟢 Disable Maintenance' if enabled else '🔴 Enable Maintenance','a:maintenance_toggle','settings',style='danger' if enabled else 'success'))
    kb.row(b('◀️ Back','adm:panel','back',style='danger'))
    await cq.answer(); await cq.message.edit_text(f"{tag('settings')} <b>Maintenance Mode</b>\n\nStatus: <b>{'ON' if enabled else 'OFF'}</b>\n\nWhen enabled, normal users are shown a maintenance message while admins retain access.",parse_mode='HTML',reply_markup=kb.as_markup())

@router.callback_query(F.data == "a:maintenance_toggle")
async def maintenance_toggle(cq, db, state):
    if not is_admin(cq.from_user.id): return
    s=await db.settings.find_one({'_id':'maintenance'}) or {'enabled':False}
    new=not bool(s.get('enabled',False))
    await db.settings.update_one({'_id':'maintenance'},{'$set':{'enabled':new}},upsert=True)
    await log_audit(db, cq.bot, admin_id=cq.from_user.id, action='MAINTENANCE', details=f"{'ON' if new else 'OFF'}")
    await cq.answer('Updated.')
    await maintenance_panel(cq,db,state)

@router.message(Command("balancehistory"))
async def balancehistory_cmd(m, db):
    if not is_admin(m.from_user.id): return
    parts=(m.text or '').split(maxsplit=1)
    if len(parts)<2: return await m.answer('Usage: /balancehistory <telegram_id|@username>')
    u=await resolve_user(db,parts[1])
    if not u: return await m.answer('❌ User not found.')
    rows=await db.balance_ledger.find({'user_id':u['telegram_id']}).sort('created_at',-1).limit(15).to_list(None)
    if not rows: return await m.answer('No balance history.')
    lines=[]
    for r in rows:
        sign='+' if float(r.get('delta',0))>=0 else ''
        lines.append(f"{sign}₹{float(r.get('delta',0)):.2f} · {escape(str(r.get('action','')))} · after ₹{float(r.get('balance_after',0)):.2f}\n{escape(str(r.get('reason','')))}")
    await m.answer(f"📋 <b>Balance History</b>\n\nUser: <b>{escape(u.get('full_name','User'))}</b>\n\n"+'\n\n'.join(lines),parse_mode='HTML')

@router.message(Command("backup"))
async def backup_cmd(m):
    if not is_admin(m.from_user.id): return
    await m.answer('🗄️ <b>Backup</b>\n\nUse your MongoDB provider snapshot/backup facility for production backups. The bot does not expose database credentials or send raw database dumps through Telegram.',parse_mode='HTML')

# ============================================================
# COMMAND SHORTCUTS
# ============================================================

@router.message(Command("editcat"))
async def editcat_cmd(m, db):
    if not is_admin(m.from_user.id):
        return
    xs = await db.categories.find({}).sort("order", 1).to_list(None)
    await m.answer(
        f"{tag('category')} <b>Categories</b>\n\nChoose a category to edit.",
        parse_mode="HTML", reply_markup=category_list_kb(xs)
    )


@router.message(Command("delcat"))
async def delcat_cmd(m, db):
    if not is_admin(m.from_user.id):
        return
    xs = await db.categories.find({}).sort("order", 1).to_list(None)
    await m.answer(
        f"{tag('category')} <b>Categories</b>\n\nChoose a category to delete.",
        parse_mode="HTML", reply_markup=category_list_kb(xs)
    )


@router.message(Command("editsub"))
async def editsub_cmd(m, db):
    if is_admin(m.from_user.id):
        await m.answer(
            f"{tag('subcategory')} <b>Sub-categories</b>\n\nChoose a category.",
            parse_mode="HTML",
            reply_markup=(await _sub_category_command_kb(db)).as_markup(),
        )


@router.message(Command("delsub"))
async def delsub_cmd(m, db):
    if is_admin(m.from_user.id):
        await m.answer(
            f"{tag('subcategory')} <b>Sub-categories</b>\n\nChoose a category.",
            parse_mode="HTML",
            reply_markup=(await _sub_category_command_kb(db)).as_markup(),
        )


async def _sub_category_command_kb(db):
    cats = await db.categories.find({}).sort("order", 1).to_list(None)
    kb = InlineKeyboardBuilder()
    for c in cats:
        kb.row(b(c["name"], f"admsubcat:{c['_id']}", "category",
                 c.get("emoji_id"), c.get("button_style", "primary")))
    kb.row(b("◀️ Back", "adm:panel", "back", style="danger"))
    return kb


@router.message(Command("editproduct"))
async def editproduct_cmd(m):
    if is_admin(m.from_user.id):
        await m.answer(
            f"{tag('products')} <b>Products</b>\n\n"
            "Open /admin → Edit Products.",
            parse_mode="HTML", reply_markup=panel_kb()
        )


@router.message(Command("delproduct"))
async def delproduct_cmd(m):
    if is_admin(m.from_user.id):
        await m.answer(
            f"{tag('products')} <b>Products</b>\n\n"
            "Open /admin → Edit Products.",
            parse_mode="HTML", reply_markup=panel_kb()
        )


@router.message(Command("user"))
async def user_cmd(m):
    if is_admin(m.from_user.id):
        await m.answer("👥 Open /admin → Users.", parse_mode="HTML", reply_markup=panel_kb())


@router.message(Command("addbalance"))
async def addbalance_cmd(m):
    if is_admin(m.from_user.id):
        await m.answer("💰 Open /admin → Users → Add Balance.", parse_mode="HTML", reply_markup=panel_kb())

@router.message(Command("setbalance"))
async def setbalance_cmd(m):
    if is_admin(m.from_user.id):
        await m.answer("💰 Open /admin → Users → Set Balance.", parse_mode="HTML", reply_markup=panel_kb())

async def _balance_command(m, db, bot, delta, action):
    if not is_admin(m.from_user.id): return
    parts=(m.text or '').split(maxsplit=3)
    if len(parts)<3:
        return await m.answer(f"Usage: /{action} <telegram_id|@username> <amount> [reason]")
    target=await resolve_user(db, parts[1])
    if not target:
        return await m.answer("❌ User not found.")
    try: amount=float(parts[2]); reason=parts[3] if len(parts)>3 else 'Admin command'
    except ValueError: return await m.answer("❌ Invalid amount.")
    if amount<=0: return await m.answer("❌ Amount must be positive.")
    try:
        u=await record_balance_change(db,user_id=target['telegram_id'],admin_id=m.from_user.id,delta=delta*amount,action=action,reason=reason)
    except ValueError:
        return await m.answer("❌ Debit failed: insufficient balance or update error.")
    await log_audit(db,bot,admin_id=m.from_user.id,action=action.upper(),target_id=target['telegram_id'],details=f"₹{amount:.2f} — {reason}")
    await m.answer(f"✅ <b>{action.title()} successful</b>\n\nUser: <b>{escape(target.get('full_name','User'))}</b>\nAmount: <b>₹{amount:.2f}</b>\nBalance: <b>₹{float(u.get('balance',0)):.2f}</b>\nReason: {escape(reason)}",parse_mode='HTML')

@router.message(Command("credit"))
async def credit_cmd(m,db,bot): await _balance_command(m,db,bot,1,'credit')

@router.message(Command("debit"))
async def debit_cmd(m,db,bot): await _balance_command(m,db,bot,-1,'debit')


# ============================================================
# SAFE GLOBAL CANCEL
# ============================================================

@router.message(Command("cancel"))
async def cancel_command(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return
    await delete_user_message(m)
    await state.clear()
    await m.answer(
        f"{tag('cancel')} <b>Cancelled.</b>\n\n"
        "Returning to the admin panel.",
        parse_mode="HTML", reply_markup=panel_kb()
    )


@router.callback_query(F.data == "adm:cancel")
async def cancel_callback(cq: CallbackQuery, state: FSMContext):
    if not is_admin(cq.from_user.id):
        return
    await state.clear()
    await cq.answer("Cancelled.")
    await cq.message.edit_text(
        f"{tag('admin')} <b>Admin Control Center</b>",
        parse_mode="HTML", reply_markup=panel_kb()
    )
