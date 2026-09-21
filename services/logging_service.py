from html import escape
from config import LOGS_CHANNEL_ID, ADMIN_LOGS_CHAT_ID


def _log_chats():
    return {cid for cid in (LOGS_CHANNEL_ID, ADMIN_LOGS_CHAT_ID) if cid}


async def log_purchase(bot, order, user, balance):
    text = (
        f'🛒 <b>NEW PURCHASE</b>\n\n'
        f'👤 {escape(user.get("full_name", "User"))}\n'
        f'🆔 <code>{user["telegram_id"]}</code>\n'
        f'🔗 @{escape(user.get("username") or "N/A")}\n\n'
        f'📦 <b>{escape(order["product_name"])}</b>\n'
        f'🔢 Qty: {order["quantity"]}\n'
        f'💰 Total: ₹{order["total"]:.2f}\n'
        f'💳 Left Balance: ₹{balance:.2f}'
    )
    for chat in _log_chats():
        try:
            await bot.send_message(chat, text, parse_mode='HTML')
        except Exception:
            pass


async def log_admin(bot, text):
    if ADMIN_LOGS_CHAT_ID:
        try:
            await bot.send_message(ADMIN_LOGS_CHAT_ID, text, parse_mode='HTML')
        except Exception:
            pass


async def log_support_report(bot, message):
    """Send a support report with user metadata and preserve the submitted media/text."""
    if not ADMIN_LOGS_CHAT_ID:
        return

    user = message.from_user
    username = f'@{escape(user.username)}' if user.username else 'N/A'
    header = (
        '🚨 <b>NEW SUPPORT REPORT</b>\n\n'
        f'👤 <b>{escape(user.full_name or "User")}</b>\n'
        f'🆔 <code>{user.id}</code>\n'
        f'🔗 {username}\n\n'
        '📩 <b>User submission:</b>'
    )

    try:
        await bot.send_message(ADMIN_LOGS_CHAT_ID, header, parse_mode='HTML')
        if message.photo:
            caption = message.caption or ''
            if caption:
                caption = f'\n\n{escape(caption)}'
            await bot.send_photo(
                ADMIN_LOGS_CHAT_ID,
                message.photo[-1].file_id,
                caption=f'🖼️ <b>Support report</b>{caption}',
                parse_mode='HTML',
            )
        elif message.text:
            await bot.send_message(
                ADMIN_LOGS_CHAT_ID,
                escape(message.text),
                parse_mode='HTML',
            )
        elif message.caption:
            await bot.send_message(
                ADMIN_LOGS_CHAT_ID,
                escape(message.caption),
                parse_mode='HTML',
            )
        else:
            await bot.copy_message(
                chat_id=ADMIN_LOGS_CHAT_ID,
                from_chat_id=message.chat.id,
                message_id=message.message_id,
            )
    except Exception:
        pass


async def log_audit(db, bot, *, admin_id, action, target_id=None, details=""):
    from datetime import datetime, timezone
    doc = {
        'admin_id': admin_id, 'action': action, 'target_id': target_id,
        'details': details[:1000], 'created_at': datetime.now(timezone.utc),
    }
    await db.audit_logs.insert_one(doc)
    await log_admin(
        bot,
        '🛡️ <b>ADMIN AUDIT</b>\n\n'
        f'Admin: <code>{admin_id}</code>\n'
        f'Action: <b>{escape(action)}</b>\n'
        f'Target: <code>{target_id if target_id is not None else "N/A"}</code>\n'
        f'Details: {escape(details[:1000])}'
    )
