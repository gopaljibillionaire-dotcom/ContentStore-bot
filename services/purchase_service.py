from datetime import datetime,timezone

async def purchase(db,bot,user,p,qty):
    if qty < 1:
        raise ValueError('INVALID_QUANTITY')
    mode = p.get('stock_mode') or ('unlimited' if p.get('stock') is None else 'single')
    if mode == 'single' and qty != 1:
        raise ValueError('SINGLE_STOCK_ONLY')
    total=round(float(p['price'])*qty,2)
    u=await db.users.find_one({'telegram_id':user})
    if not u or float(u.get('balance',0)) < total:
        raise ValueError('INSUFFICIENT_BALANCE')

    # Reserve finite stock atomically. Unlimited products do not decrement stock.
    if mode != 'unlimited':
        changed=await db.products.update_one(
            {'_id':p['_id'],'active':True,'stock':{'$gte':qty}},
            {'$inc':{'stock':-qty}}
        )
        if changed.modified_count != 1:
            raise ValueError('OUT_OF_STOCK')

    deb=await db.users.update_one(
        {'telegram_id':user,'balance':{'$gte':total}},
        {'$inc':{'balance':-total}}
    )
    if deb.modified_count != 1:
        if mode != 'unlimited':
            await db.products.update_one({'_id':p['_id']},{'$inc':{'stock':qty}})
        raise ValueError('INSUFFICIENT_BALANCE')

    order={
        'user_id':user,'product_id':p['_id'],'product_name':p['name'],
        'unit_price':float(p['price']),'quantity':qty,'total':total,
        'status':'paid','created_at':datetime.now(timezone.utc),
        'delivery_type':p.get('stock_payload_type'),
    }
    r=await db.orders.insert_one(order)
    new=await db.users.find_one({'telegram_id':user})
    return r.inserted_id,new

async def deliver_product(bot, user_id, product):
    kind=product.get('stock_payload_type')
    value=product.get('stock_payload')
    if not value:
        return False
    if kind == 'link':
        await bot.send_message(user_id, f'🔗 <b>Your product</b>\n\n{value}', parse_mode='HTML')
    elif kind == 'document':
        await bot.send_document(user_id, value, caption='📦 <b>Your product</b>', parse_mode='HTML')
    elif kind == 'photo':
        await bot.send_photo(user_id, value, caption='📦 <b>Your product</b>', parse_mode='HTML')
    elif kind == 'video':
        await bot.send_video(user_id, value, caption='📦 <b>Your product</b>', parse_mode='HTML')
    elif kind == 'audio':
        await bot.send_audio(user_id, value, caption='📦 <b>Your product</b>', parse_mode='HTML')
    elif kind == 'animation':
        await bot.send_animation(user_id, value, caption='📦 <b>Your product</b>', parse_mode='HTML')
    else:
        await bot.send_message(user_id, f'📦 <b>Your product</b>\n\n{value}', parse_mode='HTML')
    return True
