from aiogram.utils.keyboard import InlineKeyboardBuilder
from utils.buttons import btn

def panel():
    b = InlineKeyboardBuilder()
    rows = [
        ("Categories", "adm:categories", "category"),
        ("Sub-categories", "adm:subs", "subcategory"),
        ("Products", "adm:products", "products"),
        ("Stock", "adm:stock", "stock"),
        ("Orders", "adm:orders", "orders"),
        ("Users", "adm:users", "profile"),
        ("Broadcast", "adm:broadcast", "broadcast"),
        ("Force Join", "adm:forcejoin", "forcejoin"),
        ("Premium Emojis", "adm:emoji", "edit"),
        ("Statistics", "adm:stats", "stats"),
    ]
    for text, data, emoji in rows:
        b.row(btn(text, callback_data=data, emoji_key=emoji))
    return b.as_markup()

def back_panel():
    b = InlineKeyboardBuilder()
    b.row(btn("Back to Admin", callback_data="adm:panel", emoji_key="back", style="danger"))
    return b.as_markup()
