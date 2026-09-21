from datetime import datetime, timezone


async def ensure_user(db, tg):
    now = datetime.now(timezone.utc)
    await db.users.update_one(
        {'telegram_id': tg.id},
        {
            '$set': {
                'username': tg.username,
                'full_name': tg.full_name,
                'updated_at': now,
            },
            '$setOnInsert': {
                'telegram_id': tg.id,
                'balance': 0.0,
                'language': 'en',
                'created_at': now,
                'banned': False,
                'referrals': 0,
                'referral_earnings': 0.0,
            },
        },
        upsert=True,
    )
    return await db.users.find_one({'telegram_id': tg.id})


async def get_user(db, user_id):
    return await db.users.find_one({'telegram_id': user_id})


async def change_balance(db, user_id, delta):
    return await db.users.find_one_and_update(
        {'telegram_id': user_id},
        {'$inc': {'balance': float(delta)}},
        return_document=True,
    )


async def record_balance_change(db, *, user_id, admin_id, delta, action, reason=""):
    """Atomically change a user's balance and write an immutable admin ledger entry."""
    delta = round(float(delta), 2)
    if delta == 0:
        raise ValueError("ZERO_AMOUNT")
    if delta < 0:
        user = await db.users.find_one({'telegram_id': user_id})
        if not user or float(user.get('balance', 0)) < abs(delta):
            raise ValueError("INSUFFICIENT_BALANCE")
        result = await db.users.update_one(
            {'telegram_id': user_id, 'balance': {'$gte': abs(delta)}},
            {'$inc': {'balance': delta}},
        )
    else:
        result = await db.users.update_one(
            {'telegram_id': user_id}, {'$inc': {'balance': delta}}
        )
    if result.modified_count != 1:
        raise ValueError("BALANCE_UPDATE_FAILED")
    user = await db.users.find_one({'telegram_id': user_id})
    await db.balance_ledger.insert_one({
        'user_id': user_id, 'admin_id': admin_id, 'delta': delta,
        'action': action, 'reason': reason[:500],
        'balance_after': round(float(user.get('balance', 0)), 2),
        'created_at': datetime.now(timezone.utc),
    })
    return user
