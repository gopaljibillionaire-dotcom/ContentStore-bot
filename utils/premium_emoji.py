"""Central premium/custom emoji registry.

IMPORTANT:
- Static UI emojis are grouped by purpose below so an emoji ID cannot be
  accidentally reused under an unrelated button name.
- Dynamic shop objects (category/sub-category/product) keep their own
  ``emoji_id`` in MongoDB. They are NOT taken from this file.
- If a static ID is blank, Telegram receives the normal Unicode fallback.
"""

# ============================================================
# 1. USER / SHOP UI
# ============================================================
USER_EMOJI_IDS = {
    "home": "4958485609464202497",
    "products": "5395613344897979554",
    "wallet": "5215420556089776398",
    "profile": "5346024704765347251",
    "reviews": "5258353676245819106",
    "refer": "6084858306306773630",
    "support": "5305737159909581647",
    "sell": "5294049355601292129",
    "language": "5348110534157813210",
    "search": "5249245270381716113",
    "back": "5409284148491726576",
    "cancel": "5974083768233760323",
    "buy": "5269749315403802774",
    "stock": "5449872877929127395",
    "category": "5409150592188690356",
    "subcategory": "5298853345241358103",
    "loading": "5255778087437617493",
    "success": "5980930633298350051",
    "failed": "6113891550788324241",
    "warning": "6129782440157256336",
    "time": "5408910404732595664",
    "user": "5258011929993026890",
    "username": "5451715126841333904",
    "id": "5422791730443338154",
    "calendar": "6129779562529168023",
    "image": "5895427227528467580",
    "quantity": "5816654297504420784",
}

# ============================================================
# 2. ADMIN PANEL — intentionally separate from USER/SHOP
# ============================================================
ADMIN_EMOJI_IDS = {
    "admin": "6129553312241949602",
    "admin_category": "5409111052719767901",          # put Admin Categories emoji ID here
    "admin_subcategory": "5298853345241358103",       # put Admin Sub-categories emoji ID here
    "admin_product": "5193065010795911968",           # put Admin Products emoji ID here
    "admin_stock": "5449872877929127395",             # put Admin Stock emoji ID here
    "admin_orders": "5267045723685264285",
    "admin_users": "5249050854392091366",
    "admin_payments": "5796480599891907152",
    "admin_referrals": "6129727043669072880",
    "admin_premium": "6005661956931850799",
    "admin_statistics": "5203993413346680064",
    "admin_audit": "5276030241217723326",
    "admin_settings": "5258096772776991776",
    "admin_home": "5326006424839407935",
}

# ============================================================
# 3. ADMIN ACTIONS
# ============================================================
ADMIN_ACTION_EMOJI_IDS = {
    "add": "5287354223141342798",
    "edit": "5458382591121964689",
    "delete": "6129486856212979482",
    "save": "5255741073409452371",
    "confirm": "5951982867255924070",
    "danger": "5915991999093149658",
    "primary": "5913288166856462006",
    "danger_button": "5915991999093149658",
    "skip": "5199750831766784538",
    "log": "5330363643391393348",
}

# ============================================================
# 4. COMMUNICATION / BROADCAST
# ============================================================
COMMUNICATION_EMOJI_IDS = {
    "broadcast": "5399967660052081305",
    "broadcast_send": "5417876320761696693",           # optional separate Send icon
    "broadcast_success": "5409029658794537988",
    "broadcast_failed": "5348027250446967673",
}

# ============================================================
# 5. REFERRAL
# ============================================================
REFERRAL_EMOJI_IDS = {
    "referral": "6129579803600231171",
    "refer": "5368516976048104432",
    "referral_cash": "5382164415019768638",
}

# ============================================================
# 6. PAYMENTS / MONEY
# ============================================================
PAYMENT_EMOJI_IDS = {
    "money": "5296355151743838259",
    "credit": "5911101139444567404",
    "recharge": "5417924076503062111",
    "payment": "6129731974291527294",
    "upi": "6242055415010429981",
    "crypto": "5116648080787112958",
    "qr": "5422814644093868925",
    "amount": "5201873447554145566",
    "utr": "5071488806067111071",
    "cash": "6129731974291527294",
}

# ============================================================
# 7. SECURITY / FORCE JOIN / MISC
# ============================================================
MISC_EMOJI_IDS = {
    "forcejoin": "6129650743575060215",
    "verified": "5780463361175066565",
    "settings": "5258096772776991776",
    "orders": "5395613344897979554",
    "stats": "5203993413346680064",
    "calendar": "6129779562529168023",
    "time": "5408910404732595664",
    "guide": "5454093069844487380",
    "owner": "5798670723975221399",
    "report": "5408943604829794451",
}

# Flat lookup kept for compatibility with the rest of the project.
PREMIUM_IDS = {}
for _section in (
    USER_EMOJI_IDS,
    ADMIN_EMOJI_IDS,
    ADMIN_ACTION_EMOJI_IDS,
    COMMUNICATION_EMOJI_IDS,
    REFERRAL_EMOJI_IDS,
    PAYMENT_EMOJI_IDS,
    MISC_EMOJI_IDS,
):
    PREMIUM_IDS.update(_section)

# Unicode fallback for every semantic key.
EMOJI = {
    "home": "⌂", "products": "🛍️", "wallet": "💰", "profile": "👤",
    "reviews": "⭐", "refer": "🎁", "support": "🆘", "sell": "💵",
    "language": "🌐", "search": "🔎", "back": "◀️", "cancel": "❌",
    "buy": "🛒", "stock": "📦", "category": "📂", "subcategory": "🗂️",
    "admin": "🛠️", "broadcast": "📢", "forcejoin": "🔒", "add": "➕",
    "edit": "✏️", "delete": "🗑️", "save": "💾", "orders": "🧾",
    "stats": "📊", "recharge": "➕", "confirm": "✅", "danger": "⚠️",
    "money": "💳", "quantity": "🔢", "payment": "💳", "settings": "⚙️",
    "upi": "📲", "crypto": "🪙", "qr": "▣", "amount": "💵",
    "utr": "🧾", "loading": "⏳", "success": "✅", "failed": "❌",
    "warning": "⚠️", "time": "⏰", "user": "👤", "username": "🔗",
    "id": "🆔", "calendar": "📅", "credit": "💰", "image": "🖼️",
    "skip": "⏭️", "primary": "🔵", "danger_button": "🔴",
    "verified": "🔐", "log": "📋", "referral": "👥", "cash": "💸",
    "guide": "📘", "owner": "👑", "report": "🚨",
    # Scoped/admin fallbacks
    "admin_category": "📂", "admin_subcategory": "🗂️",
    "admin_product": "🛍️", "admin_stock": "📦", "admin_orders": "🧾",
    "admin_users": "👥", "admin_payments": "💳", "admin_referrals": "🎁",
    "admin_premium": "🎨", "admin_statistics": "📊", "admin_audit": "📋",
    "admin_settings": "⚙️", "admin_home": "⌂",
    "broadcast_send": "📤", "broadcast_success": "✅",
    "broadcast_failed": "❌", "referral_cash": "💸",
}

def emoji_id(key: str | None):
    if not key:
        return None
    value = str(PREMIUM_IDS.get(key, "") or "").strip()
    return value or None

def tag(key: str) -> str:
    value = emoji_id(key)
    char = EMOJI.get(key, "✨")
    if value:
        return f'<tg-emoji emoji-id="{value}">{char}</tg-emoji>'
    return char
def premium_text(
    text: str,
    emoji_map: dict[str, str] | None = None,
):
    """
    Convert selected Unicode emoji characters in `text` into Telegram
    custom-emoji entities.

    The returned text remains unchanged. Telegram uses the returned
    MessageEntity objects to render the selected characters as premium
    emojis.

    Returns:
        tuple[str, list[MessageEntity]]
    """
    from aiogram.types import MessageEntity

    if not text:
        return "", []

    if not emoji_map:
        return text, []

    def utf16_len(value: str) -> int:
        return len(value.encode("utf-16-le")) // 2

    # Prefer longer emoji sequences first so that, for example,
    # a multi-codepoint emoji is matched before one of its components.
    mappings = sorted(
        (
            (str(emoji), str(custom_id))
            for emoji, custom_id in emoji_map.items()
            if emoji and custom_id
        ),
        key=lambda item: len(item[0]),
        reverse=True,
    )

    entities = []
    occupied = []

    for emoji, custom_id in mappings:
        start = 0

        while True:
            pos = text.find(emoji, start)

            if pos == -1:
                break

            end = pos + len(emoji)

            # Don't create overlapping Telegram entities.
            overlaps = any(
                pos < existing_end and end > existing_start
                for existing_start, existing_end in occupied
            )

            if not overlaps:
                entities.append(
                    MessageEntity(
                        type="custom_emoji",
                        offset=utf16_len(text[:pos]),
                        length=utf16_len(emoji),
                        custom_emoji_id=custom_id,
                    )
                )

                occupied.append((pos, end))

            start = end

    entities.sort(key=lambda entity: entity.offset)

    return text, entities