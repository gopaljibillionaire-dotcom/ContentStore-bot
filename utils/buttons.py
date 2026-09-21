from __future__ import annotations

from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from utils.premium_emoji import EMOJI, emoji_id

BUTTON_STYLES = {"primary": "primary", "success": "success", "danger": "danger"}


def _strip_button_emoji(text: str, emoji_key: str | None) -> str:
    """Remove the Unicode fallback from a button when a custom emoji icon is used."""
    if not emoji_key:
        return text
    fallback = EMOJI.get(emoji_key)
    if not fallback:
        return text
    value = text.strip()
    if value.startswith(fallback):
        value = value[len(fallback):].lstrip()
    return value


def btn(text, callback_data=None, url=None, emoji_key=None, style=None, custom_emoji_id=None):
    kwargs = {}
    eid = custom_emoji_id or emoji_id(emoji_key)
    # Telegram renders icon_custom_emoji_id separately from button text.
    # Therefore never leave the matching Unicode fallback in the text too.
    kwargs["text"] = _strip_button_emoji(str(text), emoji_key) if eid else text
    if callback_data is not None:
        kwargs["callback_data"] = callback_data
    if url is not None:
        kwargs["url"] = url
    if eid:
        kwargs["icon_custom_emoji_id"] = str(eid)
    if style in BUTTON_STYLES:
        kwargs["style"] = style
    return InlineKeyboardButton(**kwargs)


def nav(back="home", back_text="Back"):
    b = InlineKeyboardBuilder()
    b.row(btn(back_text, callback_data=back, emoji_key="back", style="danger"))
    return b.as_markup()
