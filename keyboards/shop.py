from aiogram.utils.keyboard import InlineKeyboardBuilder
from utils.buttons import btn
from locales.i18n import T

def category_kb(items, lang="en", back="home"):
    x = T.get(lang, T["en"])
    b = InlineKeyboardBuilder()
    for i in items:
        b.row(btn(
            i["name"],
            callback_data=f"cat:{i['_id']}",
            emoji_key="category",
            custom_emoji_id=i.get("emoji_id"),
            style=i.get("button_style", "primary"),
        ))
    b.row(btn(x["search"], callback_data="search", emoji_key="search"))
    b.row(btn(x["back"], callback_data=back, emoji_key="back", style="danger"))
    return b.as_markup()

def sub_kb(items, cat, lang="en", back="products"):
    x = T.get(lang, T["en"])
    b = InlineKeyboardBuilder()
    for i in items:
        b.row(btn(
            i["name"],
            callback_data=f"sub:{i['_id']}:{cat}",
            emoji_key="subcategory",
            custom_emoji_id=i.get("emoji_id"),
            style=i.get("button_style", "primary"),
        ))
    b.row(btn(x["back"], callback_data=back, emoji_key="back", style="danger"))
    return b.as_markup()

def product_kb(items, back, lang="en", emoji_key="buy"):
    x = T.get(lang, T["en"])
    b = InlineKeyboardBuilder()

    for i in items:
        pid = str(i["_id"])

        b.row(btn(
            i["name"],
            callback_data=f"prod:{pid}",
            emoji_key=emoji_key,
            custom_emoji_id=i.get("emoji_id"),
            style=i.get("button_style", "primary"),
        ))

    b.row(
        btn(
            x["back"],
            callback_data=back,
            emoji_key="back",
            style="danger",
        )
    )

    return b.as_markup()

def product_detail_kb(pid, lang="en", back="products", sub_id=None):
    x = T.get(lang, T["en"])
    b = InlineKeyboardBuilder()
    b.row(
        btn(x["buy1"], callback_data=f"buy:{pid}:1:{sub_id or ''}", emoji_key="buy", style="success"),
        btn(x["buy2"], callback_data=f"buy:{pid}:2:{sub_id or ''}", emoji_key="buy", style="success"),
    )
    b.row(btn(x["custom"], callback_data=f"custom:{pid}:{sub_id or ''}", emoji_key="quantity"))
    b.row(
        btn(x["back"], callback_data=back, emoji_key="back", style="danger"),
        btn(x["cancel"], callback_data="home", emoji_key="cancel", style="danger"),
    )
    return b.as_markup()


def purchase_success_kb(lang="en"):
    x = T.get(lang, T["en"])

    b = InlineKeyboardBuilder()

    b.row(
        btn(
            x["home"],
            callback_data="home",
            emoji_key="home",
            style="primary",
        ),
        btn(
            x["support"],
            callback_data="support",
            emoji_key="support",
            style="primary",
        ),
    )

    return b.as_markup()