"""Recharge/payment router for the content-selling bot.

Supports:
- UPI manual screenshot -> admin approval
- UPI auto UTR verification through a configurable API
- Crypto manual screenshot -> admin approval
- Crypto auto via OxaPay API (configurable)
- Admin payment controls/settings

Secrets are read from .env; no credentials are hard-coded.
"""
import io
import os
from datetime import datetime, timezone
from html import escape

import aiohttp
import qrcode
from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from utils.buttons import btn
from utils.premium_emoji import tag

from config import ADMIN_IDS
from payments.oxapay import create_invoice, check_invoice, status_from_response

router = Router()

class RechargeState(StatesGroup):
    upi_amount = State()
    upi_screenshot = State()
    auto_upi_amount = State()
    auto_upi_utr = State()
    crypto_amount = State()
    manual_method = State()
    manual_screenshot = State()
    manual_usdt_amount = State()
    admin_value = State()
    admin_qr = State()


def _now():
    return datetime.now(timezone.utc)

async def get_settings(db):
    s = await db.settings.find_one({'_id': 'payments'})
    defaults = {
        '_id': 'payments',
        'payments_active': True,
        'upi_active': True,
        'usdt_active': True,
        'upi_id': os.getenv('UPI_ID', ''),
        'upi_qr_file_id': os.getenv('UPI_QR_FILE_ID', ''),
        'min_upi': float(os.getenv('MIN_UPI', '5')),
        'min_usdt': float(os.getenv('MIN_USDT', '0.1')),
        'usdt_rate': float(os.getenv('USDT_RATE', '90')),
        'binance_pay_id': os.getenv('BINANCE_PAY_ID', ''),
        'cwallet_id': os.getenv('CWALLET_ID', ''),
    }
    if not s:
        await db.settings.insert_one(defaults)
        return defaults
    changed = False
    for k, v in defaults.items():
        if k not in s:
            s[k] = v; changed = True
    if changed:
        await db.settings.update_one({'_id':'payments'}, {'$set': {k:v for k,v in s.items() if k != '_id'}})
    return s

async def live_usdt_rate(fallback):
    try:
        timeout = aiohttp.ClientTimeout(total=5)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get('https://api.coingecko.com/api/v3/simple/price', params={'ids':'tether','vs_currencies':'inr'}) as r:
                if r.status == 200:
                    data = await r.json()
                    return float(data['tether']['inr'])
    except Exception as e:
        print('USDT rate error:', e)
    return float(fallback)

async def credit_balance(db, user_id, amount):
    await db.users.update_one({'telegram_id': user_id}, {'$inc': {'balance': float(amount)}})
    u = await db.users.find_one({'telegram_id': user_id}, {'balance':1})
    return float((u or {}).get('balance', 0))

async def referral_bonus(bot, db, user_id, amount):
    """Legacy compatibility: referrals are credited once per successful referral.

    The fixed reward is handled by handlers.start.finalize_referral, so deposits
    must not create an additional percentage-based referral bonus.
    """
    return

async def notify_admin_payment(bot, tx, *, status="approved"):
    """Send one complete payment log to every admin."""
    created=tx.get("created_at") or _now()
    if hasattr(created, "astimezone"):
        try: created=created.astimezone().strftime("%d-%m-%Y %H:%M:%S %Z")
        except Exception: created=str(created)
    else:
        created=str(created)
    username=tx.get("username") or "N/A"
    if username != "N/A": username="@"+str(username).lstrip("@")
    method=str(tx.get("method", "payment")).replace("_", " ").title()
    text=(
        f"{tag('success') if status == 'approved' else tag('warning')} <b>Payment Received</b>\n\n"
        f"{tag('payment')} <b>Method:</b> {escape(method)}\n"
        f"{tag('user')} <b>Name:</b> {escape(str(tx.get('full_name') or 'N/A'))}\n"
        f"{tag('username')} <b>Username:</b> {escape(username)}\n"
        f"{tag('id')} <b>User ID:</b> <code>{tx.get('user_id')}</code>\n"
        f"{tag('amount')} <b>Amount Added:</b> ₹{float(tx.get('amount',0)):.2f}\n"
    )
    if tx.get('utr'):
        text += f"{tag('utr')} <b>UTR:</b> <code>{escape(str(tx['utr']))}</code>\n"
    if tx.get('transaction_id'):
        text += f"{tag('utr')} <b>Transaction ID:</b> <code>{escape(str(tx['transaction_id']))}</code>\n"
    if tx.get('track_id'):
        text += f"{tag('id')} <b>OxaPay Track ID:</b> <code>{escape(str(tx['track_id']))}</code>\n"
    text += f"{tag('time')} <b>Date/Time:</b> {escape(created)}\n"
    for admin in ADMIN_IDS:
        try:
            await bot.send_message(admin, text, parse_mode='HTML')
        except Exception as exc:
            print('Admin payment log error:', exc)


async def payment_menu(cq, db):
    s = await get_settings(db)

    if not s.get('payments_active', True):
        return await cq.answer(
            '⚠️ Payments are currently unavailable.',
            show_alert=True
        )

    b = InlineKeyboardBuilder()

    if s.get('upi_active', True):
        b.row(
            btn(
                'UPI (Auto)',
                callback_data='pay:auto_upi',
                emoji_key='upi',
                style='success'
            )
        )
        b.row(
            btn(
                'UPI (Manual)',
                callback_data='pay:upi',
                emoji_key='upi'
            )
        )

    if s.get('usdt_active', True):
        b.row(
            btn(
                'Crypto (Auto)',
                callback_data='pay:crypto',
                emoji_key='crypto',
                style='success'
            )
        )
        b.row(
            btn(
                'Crypto (Manual)',
                callback_data='pay:manual',
                emoji_key='crypto'
            )
        )

    b.row(
        btn(
            'Back',
            callback_data='wallet',
            emoji_key='back',
            style='danger'
        )
    )

    text = (
        f'{tag("payment")} <b>Add Balance</b>\n\n'
        'Choose a payment method:'
    )

    # Payment screens can be photo messages.
    try:
        await cq.message.edit_text(
            text,
            parse_mode='HTML',
            reply_markup=b.as_markup()
        )
    except Exception:
        try:
            await cq.message.delete()
        except Exception:
            pass

        await cq.message.answer(
            text,
            parse_mode='HTML',
            reply_markup=b.as_markup()
        )

@router.callback_query(F.data == 'recharge')
async def recharge_back(cq: CallbackQuery, state: FSMContext, db):
    await state.clear()
    await payment_menu(cq, db)
    await cq.answer()

@router.message(Command('recharge'))
async def recharge_cmd(m, db):
    # Reuse wallet-style message without requiring a callback target.
    s = await get_settings(db)
    if not s.get('payments_active', True): return await m.answer('⚠️ Payments are currently unavailable.')
    b=InlineKeyboardBuilder(); b.row(btn('UPI (Auto)',callback_data='pay:auto_upi',emoji_key='upi')); b.row(btn('UPI (Manual)',callback_data='pay:upi',emoji_key='upi')); b.row(btn('Crypto (Auto)',callback_data='pay:crypto',emoji_key='crypto')); b.row(btn('Crypto (Manual)',callback_data='pay:manual',emoji_key='crypto')); b.adjust(2)
    await m.answer('💳 <b>Add Balance</b>\n\nChoose a payment method:',parse_mode='HTML',reply_markup=b.as_markup())

@router.callback_query(F.data == 'pay:upi')
async def manual_upi(cq, state, db):
    s = await get_settings(db)

    if not s.get('upi_active', True):
        return await cq.answer('UPI is unavailable.', show_alert=True)

    b = InlineKeyboardBuilder()
    b.row(
        btn(
            'Payment Done',
            callback_data='upi_done',
            emoji_key='confirm',
            style='success'
        )
    )
    b.row(
        btn(
            'Back',
            callback_data='recharge',
            emoji_key='back'
        )
    )

    qr = s.get('upi_qr_file_id')

    caption = (
        f'📲 <b>UPI Payment</b>\n\n'
        f'UPI ID: <code>{escape(s.get("upi_id") or "Not configured")}</code>\n\n'
        f'Pay and tap <b>Payment Done</b>. Then send the screenshot.'
    )

    # Remove the old payment-menu message
    try:
        await cq.message.delete()
    except Exception:
        pass

    if qr:
        msg = await cq.message.answer_photo(
            qr,
            caption=caption,
            parse_mode='HTML',
            reply_markup=b.as_markup()
        )
    else:
        msg = await cq.message.answer(
            caption + '\n\n⚠️ Admin has not uploaded a QR yet.',
            parse_mode='HTML',
            reply_markup=b.as_markup()
        )

    await state.update_data(last_msg=msg.message_id)

    await cq.answer()

@router.callback_query(F.data == 'pay_back')
async def pay_back(cq: CallbackQuery, state: FSMContext, db):
    await state.clear()
    await payment_menu(cq, db)
    await cq.answer()

@router.callback_query(F.data == 'pay_home')
async def pay_home(cq: CallbackQuery, state: FSMContext):
    await state.clear()

    try:
        await cq.message.delete()
    except Exception:
        pass

    # Let your main home handler handle the actual home screen.
    await cq.answer()

    try:
        await cq.message.answer(
            "<b>/start to continute...</b>",
            parse_mode="HTML"
        )
    except Exception:
        pass

@router.callback_query(F.data == 'upi_done')
async def upi_done(cq,state):
    try:
        await cq.message.edit_caption(caption='💰 <b>Enter amount sent (INR)</b>',parse_mode='HTML',reply_markup=None)
    except Exception:
        await cq.message.edit_text('💰 <b>Enter amount sent (INR)</b>',parse_mode='HTML',reply_markup=None)
    await state.update_data(last_msg=cq.message.message_id)
    await state.set_state(RechargeState.upi_amount)

@router.message(RechargeState.upi_amount)
async def upi_amount(m,state,db,bot):
    if not m.text or not m.text.strip().replace('.','',1).isdigit(): return await m.answer('❌ Enter a valid amount.')
    s=await get_settings(db); amount=float(m.text.strip())
    if amount < float(s.get('min_upi',5)): return await m.answer(f'❌ Minimum is ₹{s.get("min_upi",5)}.')
    try: await m.delete()
    except: pass
    d=await state.get_data()
    mid=d.get('last_msg')
    try:
        await bot.edit_message_caption(chat_id=m.chat.id,message_id=mid,caption=f'📸 <b>Send your payment screenshot now</b>\n\nAmount: <b>₹{amount:.2f}</b>',parse_mode='HTML')
    except Exception:
        await bot.edit_message_text(chat_id=m.chat.id,message_id=mid,text=f'📸 <b>Send your payment screenshot now</b>\n\nAmount: <b>₹{amount:.2f}</b>',parse_mode='HTML')
    await state.update_data(amount=amount,last_msg=mid)
    await state.set_state(RechargeState.upi_screenshot)

@router.message(RechargeState.upi_screenshot, F.photo)
async def upi_screenshot(m,state,db,bot):
    d=await state.get_data(); amount=float(d['amount'])
    tid=await db.transactions.insert_one({'user_id':m.from_user.id,'username':m.from_user.username,'full_name':m.from_user.full_name,'amount':amount,'method':'upi_manual','status':'pending','proof_file_id':m.photo[-1].file_id,'created_at':_now()})
    b=InlineKeyboardBuilder(); b.row(btn('Approve',callback_data=f'approve_txn:{tid.inserted_id}',emoji_key='confirm',style='success'), btn('Decline',callback_data=f'decline_txn:{tid.inserted_id}',emoji_key='delete',style='danger'))
    for admin in ADMIN_IDS:
        try: await bot.send_photo(admin,m.photo[-1].file_id,caption=f'🧾 <b>UPI Manual</b>\nUser: {escape(m.from_user.full_name)}\nID: <code>{m.from_user.id}</code>\nAmount: ₹{amount:.2f}',parse_mode='HTML',reply_markup=b.as_markup())
        except Exception as e: print('Admin payment notify:',e)
    try: await m.delete()
    except: pass
    mid=d.get('last_msg')
    try:
        await bot.edit_message_caption(chat_id=m.chat.id,message_id=mid,caption='✅ <b>Deposit submitted</b>\n\nYour payment proof is pending admin approval.',parse_mode='HTML',reply_markup=None)
    except Exception:
        await bot.edit_message_text(chat_id=m.chat.id,message_id=mid,text='✅ <b>Deposit submitted</b>\n\nYour payment proof is pending admin approval.',parse_mode='HTML',reply_markup=None)
    await state.clear()


@router.callback_query(F.data == 'pay:auto_upi')
async def auto_upi_start(cq,state,db):
    await cq.answer(
        "⚠️ Auto UPI is currently unavailable.",
        show_alert=True,
         )
    return
    s=await get_settings(db)
    if not s.get('upi_active',True): return await cq.answer('UPI is unavailable.',show_alert=True)
    await cq.message.edit_text(f'💰 Enter recharge amount in INR (minimum ₹{s.get("min_upi",5)}):'); await state.set_state(RechargeState.auto_upi_amount)

@router.message(RechargeState.auto_upi_amount)
async def auto_upi_amount(m,state,db,bot):
    await cq.answer(
        "⚠️ Auto UPI is currently unavailable.",
        show_alert=True,
         )
    return
    try: amount=float(m.text.strip())
    except: return await m.answer('❌ Invalid amount.')
    s=await get_settings(db)
    if amount < float(s.get('min_upi',5)): return await m.answer(f'❌ Minimum is ₹{s.get("min_upi",5)}.')
    upi=s.get('upi_id')
    if not upi: return await m.answer('⚠️ Auto UPI is not configured.')
    qr=qrcode.QRCode(box_size=10,border=2); qr.add_data(f'upi://pay?pa={upi}&am={amount:.2f}&cu=INR'); qr.make(fit=True)
    img=qr.make_image(fill_color='black',back_color='white').convert('RGB'); buf=io.BytesIO(); img.save(buf,format='PNG'); buf.seek(0)
    b=InlineKeyboardBuilder(); b.row(btn('I Have Paid',callback_data='auto_upi_paid',emoji_key='confirm',style='success')); b.row(btn('Cancel',callback_data='home',emoji_key='cancel',style='danger'))
    d=await state.get_data()
    try: await m.delete()
    except: pass
    old_id=d.get('last_msg')
    try: await bot.delete_message(m.chat.id,old_id)
    except: pass
    msg=await m.answer_photo(BufferedInputFile(buf.read(),'upi.png'),caption=f'{tag("upi")} <b>Auto UPI</b>\n\nID: <code>{escape(upi)}</code>\n{tag("amount")} <b>Amount:</b> ₹{amount:.2f}\n\nPay the exact amount and submit your UTR.',parse_mode='HTML',reply_markup=b.as_markup())
    await state.update_data(amount=amount,last_msg=msg.message_id)
    await state.set_state(RechargeState.auto_upi_utr)

@router.callback_query(F.data == 'auto_upi_paid')
async def auto_paid(cq,state):
    try:
        await cq.message.edit_caption(caption=f'{tag("utr")} <b>Enter UTR / Transaction ID</b>\n\nSend the UTR/transaction ID from your payment app.',parse_mode='HTML',reply_markup=None)
    except Exception:
        await cq.message.edit_text(f'{tag("utr")} <b>Enter UTR / Transaction ID</b>\n\nSend the UTR/transaction ID from your payment app.',parse_mode='HTML',reply_markup=None)
    await state.update_data(last_msg=cq.message.message_id)
    await state.set_state(RechargeState.auto_upi_utr)

@router.message(RechargeState.auto_upi_utr)
async def auto_verify(m,state,db,bot):
    d=await state.get_data(); amount=float(d['amount']); utr=(m.text or '').strip()
    if not utr:
        return await m.answer(f'{tag("failed")} <b>Enter a valid UTR.</b>',parse_mode='HTML')
    try: await m.delete()
    except Exception: pass
    mid=d.get('last_msg')
    async def update_status(text):
        try:
            await bot.edit_message_caption(chat_id=m.chat.id,message_id=mid,caption=text,parse_mode='HTML',reply_markup=None)
        except Exception:
            try: await bot.edit_message_text(chat_id=m.chat.id,message_id=mid,text=text,parse_mode='HTML',reply_markup=None)
            except Exception: pass
    await update_status(f'{tag("loading")} <b>Auto verifying your payment...</b>\n\nPlease wait while we verify the UTR.')
    existing=await db.transactions.find_one({'$or':[{'utr':utr},{'transaction_id':utr}],'status':'approved'})
    if existing:
        await update_status(f'{tag("failed")} <b>This UTR has already been used.</b>')
        await state.clear(); return
    email=os.getenv('AUTO_UPI_EMAIL',''); apppass=os.getenv('AUTO_UPI_APP_PASSWORD',''); endpoint=os.getenv('AUTO_UPI_VERIFY_URL','')
    if not endpoint or not email or not apppass:
        await update_status(f'{tag("warning")} <b>Auto UPI verification is not configured.</b>\n\nPlease use Manual UPI.')
        await state.clear(); return
    params={'mail':email,'apppass':apppass,'amount':str(amount)}
    params['txnid' if utr.upper().startswith('FMP') else 'utr']=utr
    try:
        timeout=aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(endpoint,params=params) as r:
                data=await r.json(content_type=None)
    except Exception as e:
        print('Auto UPI error:',e)
        await update_status(f'{tag("failed")} <b>Verification service unavailable.</b>\n\nPlease try again or use Manual UPI.')
        await state.clear(); return
    found=str(data.get('status','')).lower()=='found' or str(data.get('result','')).lower()=='found'
    if not found:
        await update_status(f'{tag("failed")} <b>Payment not found.</b>\n\nCheck the UTR and try again.')
        await state.clear(); return
    tx={
        'user_id':m.from_user.id,'username':m.from_user.username,'full_name':m.from_user.full_name,
        'amount':amount,'method':'upi_auto','utr':str(data.get('utr',utr)),
        'transaction_id':str(data.get('transaction_id',utr)),'status':'approved','created_at':_now(),
    }
    result=await db.transactions.insert_one(tx); tx['_id']=result.inserted_id
    bal=await credit_balance(db,m.from_user.id,amount)
    await state.clear()
    await update_status(f'{tag("success")} <b>Payment Received!</b>\n\n{tag("utr")} <b>UTR:</b> <code>{escape(tx["utr"])}</code>\n{tag("amount")} <b>Added:</b> ₹{amount:.2f}\n{tag("money")} <b>New Balance:</b> ₹{bal:.2f}')
    await notify_admin_payment(bot,tx,status='approved')

@router.callback_query(F.data == 'pay:manual')
async def manual_crypto(cq,state,db):
    s=await get_settings(db); rate=await live_usdt_rate(s.get('usdt_rate',90)); await state.update_data(rate=rate)
    b=InlineKeyboardBuilder(); b.row(btn('Binance Pay',callback_data='manual:Binance',emoji_key='crypto')); b.row(btn('Cwallet',callback_data='manual:Cwallet',emoji_key='crypto')); b.row(btn('Back',callback_data='recharge',emoji_key='back',style='danger'))
    await cq.message.edit_text(f'🪙 <b>Manual Crypto Deposit</b>\n\nLive rate: <b>1 USDT = ₹{rate:.2f}</b>\n\nChoose a wallet:',parse_mode='HTML',reply_markup=b.as_markup())

@router.callback_query(F.data.startswith('manual:'))
async def manual_wallet(cq,state,db):
    method=cq.data.split(':',1)[1]; s=await get_settings(db); d=await state.get_data(); rate=d.get('rate',s.get('usdt_rate',90)); pay=s.get('binance_pay_id' if method=='Binance' else 'cwallet_id','')
    await state.update_data(method=method,rate=rate)
    b=InlineKeyboardBuilder(); b.row(btn('I Have Paid',callback_data='manual_paid',emoji_key='confirm',style='success')); b.row(btn('Back',callback_data='pay:manual',emoji_key='back')); b.row(btn('Cancel',callback_data='home',emoji_key='cancel',style='danger'))
    await cq.message.edit_text(f'🪙 <b>{method} Pay</b>\n\nID: <code>{escape(pay or "Not configured")}</code>\nRate: <b>1 USDT = ₹{rate:.2f}</b>\n\nTransfer funds and tap <b>I Have Paid</b>.',parse_mode='HTML',reply_markup=b.as_markup())
    await state.update_data(last_msg=cq.message.message_id)

@router.callback_query(F.data == 'manual_paid')
async def manual_paid(cq,state):
    await cq.message.edit_text('📸 <b>Send payment screenshot</b>',parse_mode='HTML')
    await state.update_data(last_msg=cq.message.message_id)
    await state.set_state(RechargeState.manual_screenshot)

@router.message(RechargeState.manual_screenshot, F.photo)
async def manual_ss(m,state,bot):
    d=await state.get_data()
    await state.update_data(proof=m.photo[-1].file_id)
    try: await m.delete()
    except: pass
    mid=d.get('last_msg')
    try: await bot.edit_message_text(chat_id=m.chat.id,message_id=mid,text='💵 <b>How much USDT did you send?</b>\n\nExample: <code>10</code> or <code>50.5</code>',parse_mode='HTML')
    except Exception: pass
    await state.set_state(RechargeState.manual_usdt_amount)

@router.message(RechargeState.manual_usdt_amount)
async def manual_usdt(m,state,db,bot):
    try: usdt=float(m.text.strip())
    except: return await m.answer('❌ Invalid USDT amount.')
    d=await state.get_data(); rate=float(d.get('rate',90)); inr=round(usdt*rate,2)
    try: await m.delete()
    except: pass
    r=await db.transactions.insert_one({'user_id':m.from_user.id,'username':m.from_user.username,'full_name':m.from_user.full_name,'amount':inr,'usdt_amount':usdt,'method':f'{d.get("method","Crypto")}_manual','status':'pending','proof_file_id':d.get('proof'),'created_at':_now()})
    b=InlineKeyboardBuilder(); b.row(btn('Approve',callback_data=f'approve_txn:{r.inserted_id}',emoji_key='confirm',style='success'), btn('Decline',callback_data=f'decline_txn:{r.inserted_id}',emoji_key='delete',style='danger'))
    for admin in ADMIN_IDS:
        try: await bot.send_photo(admin,d.get('proof'),caption=f'💎 <b>Manual Crypto</b>\nUser: {escape(m.from_user.full_name)}\nID: <code>{m.from_user.id}</code>\nMethod: {escape(d.get("method","Crypto"))}\nSent: {usdt:g} USDT\nCredit: ₹{inr:.2f}',parse_mode='HTML',reply_markup=b.as_markup())
        except Exception as e: print('Manual crypto notify:',e)
    mid=d.get('last_msg')
    try: await bot.edit_message_text(chat_id=m.chat.id,message_id=mid,text=f'✅ <b>Request submitted</b>\n\nCredit on approval: ₹{inr:.2f}',parse_mode='HTML')
    except Exception: await m.answer(f'✅ Request submitted.\n\nCredit on approval: ₹{inr:.2f}',parse_mode='HTML')
    await state.clear()

@router.callback_query(F.data == 'pay:crypto')
async def crypto_auto(cq,state,db):
    s=await get_settings(db)
    if not os.getenv('OXAPAY_MERCHANT_API_KEY'):
        return await cq.answer('⚠️ OxaPay is not configured. Use Manual Crypto.',show_alert=True)
    await cq.message.edit_text(
        f'🪙 <b>Crypto Auto Deposit</b>\n\nSend the amount in USDT.\nMinimum: <b>{s.get("min_usdt",0.1):g} USDT</b>',
        parse_mode='HTML',
        reply_markup=InlineKeyboardBuilder().row(btn('Cancel',callback_data='home',emoji_key='cancel',style='danger')).as_markup(),
    )
    await state.update_data(last_msg=cq.message.message_id)
    await state.set_state(RechargeState.crypto_amount)


@router.message(RechargeState.crypto_amount)
async def crypto_amount(m,state,db,bot):
    try:
        usdt=float((m.text or '').strip())
    except Exception:
        return await m.answer('❌ Enter a valid amount.')
    s=await get_settings(db)
    if usdt < float(s.get('min_usdt',0.1)):
        return await m.answer(f'❌ Minimum is {s.get("min_usdt",0.1):g} USDT.')

    order=f'RECHARGE-{m.from_user.id}-{int(datetime.now().timestamp())}'
    result=await create_invoice(usdt, order)
    try: await m.delete()
    except Exception: pass
    if not result.get('success'):
        return await bot.edit_message_text(
            chat_id=m.chat.id, message_id=(await state.get_data()).get('last_msg', 0),
            text=f'❌ <b>Could not create invoice</b>\n\n{escape(str(result.get("error","Unknown error")))}',
            parse_mode='HTML',
            reply_markup=InlineKeyboardBuilder().row(btn('Back',callback_data='recharge',emoji_key='back',style='danger')).as_markup(),
        )

    data=result.get('data') or {}
    pay_url=data.get('payment_url') or data.get('payLink') or data.get('paymentUrl')
    track=data.get('track_id') or data.get('trackId')
    if not pay_url or not track:
        return await bot.edit_message_text(
            chat_id=m.chat.id, message_id=(await state.get_data()).get('last_msg', 0),
            text='❌ <b>OxaPay returned an incomplete invoice.</b>\n\nPlease try again or use Manual Crypto.',
            parse_mode='HTML', reply_markup=InlineKeyboardBuilder().row(btn('Back',callback_data='recharge',emoji_key='back',style='danger')).as_markup(),
        )

    rate=await live_usdt_rate(s.get('usdt_rate',90)); inr=round(usdt*rate,2)
    await db.transactions.insert_one({
        'user_id':m.from_user.id,'username':m.from_user.username,'full_name':m.from_user.full_name,
        'amount':inr,'usdt_amount':usdt,'method':'crypto_auto','track_id':str(track),
        'order_id':order,'status':'pending','created_at':_now(),
    })
    b=InlineKeyboardBuilder()
    b.row(btn('Pay Now',url=pay_url,emoji_key='money',style='success'))
    b.row(btn('Check Payment',callback_data=f'crypto_check:{track}',emoji_key='confirm'))
    b.row(btn('Cancel',callback_data='home',emoji_key='cancel',style='danger'))
    b.adjust(1)
    await bot.edit_message_text(
        chat_id=m.chat.id,message_id=(await state.get_data()).get('last_msg',0),
        text=f'🪙 <b>Crypto Invoice</b>\n\nAmount: <b>{usdt:g} USDT</b>\nValue: <b>₹{inr:.2f}</b>\nExpires: <b>30 minutes</b>\n\nTap <b>Pay Now</b>. After payment, the bot will verify it automatically.',
        parse_mode='HTML',reply_markup=b.as_markup())
    await state.clear()


async def _credit_crypto_transaction(db,bot,tx):
    """Atomically mark a pending invoice paid, then credit once."""
    from bson import ObjectId
    changed=await db.transactions.find_one_and_update(
        {'_id':tx['_id'],'status':'pending'},
        {'$set':{'status':'approved','approved_at':_now()}},
        return_document=__import__('pymongo').ReturnDocument.AFTER,
    )
    if not changed:
        return False
    bal=await credit_balance(db,changed['user_id'],changed['amount'])
    try:
        await bot.send_message(changed['user_id'],f'{tag("success")} <b>Payment Received</b>\n\n{tag("amount")} <b>Added:</b> ₹{changed["amount"]:.2f}\n{tag("money")} <b>New Balance:</b> ₹{bal:.2f}',parse_mode='HTML')
    except Exception:
        pass
    await notify_admin_payment(bot,changed,status='approved')
    return True


@router.callback_query(F.data.startswith('crypto_check:'))
async def crypto_check(cq,db,bot):
    track=cq.data.split(':',1)[1]
    tx=await db.transactions.find_one({'track_id':track})
    if not tx:
        return await cq.answer('Invoice not found.',show_alert=True)
    if tx.get('status')=='approved':
        return await cq.answer('Payment already credited.',show_alert=True)
    response=await check_invoice(track)
    status=status_from_response(response)
    if status in {'paid','manual_accept'}:
        await _credit_crypto_transaction(db,bot,tx)
        await cq.message.edit_text(f'{tag("success")} <b>Payment confirmed</b>\n\nYour balance has been credited.',parse_mode='HTML',reply_markup=InlineKeyboardBuilder().row(btn('Home',callback_data='home',emoji_key='home',style='success')).as_markup())
        return await cq.answer('Payment confirmed')
    if status in {'expired','refunded','refunding'}:
        await db.transactions.update_one({'_id':tx['_id'],'status':'pending'},{'$set':{'status':status}})
        return await cq.answer(f'Invoice status: {status}.',show_alert=True)
    await cq.answer('Payment is not confirmed yet. Please try again in a few seconds.',show_alert=True)


async def oxapay_reconciliation_loop(db,bot):
    """Background reconciliation so users do not have to press Check Payment."""
    import asyncio
    while True:
        if not os.getenv('OXAPAY_MERCHANT_API_KEY'):
            await asyncio.sleep(30)
            continue
        try:
            cursor=db.transactions.find({'method':'crypto_auto','status':'pending','track_id':{'$exists':True}}).limit(50)
            async for tx in cursor:
                response=await check_invoice(str(tx['track_id']))
                status=status_from_response(response)
                if status in {'paid','manual_accept'}:
                    await _credit_crypto_transaction(db,bot,tx)
                elif status in {'expired','refunded','refunding'}:
                    await db.transactions.update_one({'_id':tx['_id'],'status':'pending'},{'$set':{'status':status}})
        except Exception as exc:
            print('OxaPay reconciliation error:',exc)
        await asyncio.sleep(int(os.getenv('OXAPAY_POLL_SECONDS','15')))



@router.callback_query(F.data.startswith('approve_txn:'))
async def approve_txn(cq,db,bot):
    if cq.from_user.id not in ADMIN_IDS: return await cq.answer('Denied',show_alert=True)
    from bson import ObjectId
    try: oid=ObjectId(cq.data.split(':',1)[1])
    except: return await cq.answer('Invalid transaction.',show_alert=True)
    tx=await db.transactions.find_one_and_update({'_id':oid,'status':'pending'},{'$set':{'status':'approved','approved_at':_now()}},return_document=__import__('pymongo').ReturnDocument.AFTER)
    if not tx: return await cq.answer('Already processed.',show_alert=True)
    bal=await credit_balance(db,tx['user_id'],tx['amount'])
    await bot.send_message(tx['user_id'],f'{tag("success")} <b>Deposit Approved</b>\n\n{tag("amount")} <b>Added:</b> ₹{tx["amount"]:.2f}\n{tag("money")} <b>New Balance:</b> ₹{bal:.2f}',parse_mode='HTML')
    await notify_admin_payment(bot,tx,status='approved')
    try: await cq.message.edit_reply_markup(reply_markup=None)
    except: pass
    await cq.answer('Approved')

@router.callback_query(F.data.startswith('decline_txn:'))
async def decline_txn(cq,db,bot):
    if cq.from_user.id not in ADMIN_IDS: return await cq.answer('Denied',show_alert=True)
    from bson import ObjectId
    try: oid=ObjectId(cq.data.split(':',1)[1])
    except: return await cq.answer('Invalid transaction.',show_alert=True)
    tx=await db.transactions.find_one_and_update({'_id':oid,'status':'pending'},{'$set':{'status':'declined','declined_at':_now()}},return_document=__import__('pymongo').ReturnDocument.AFTER)
    if not tx: return await cq.answer('Already processed.',show_alert=True)
    try: await bot.send_message(tx['user_id'],'❌ Your deposit request was declined. Please contact support if you believe this is incorrect.')
    except: pass
    try: await cq.message.edit_reply_markup(reply_markup=None)
    except: pass
    await cq.answer('Declined')

@router.message(Command('setpay'))
async def setpay_cmd(m,db):
    if m.from_user.id not in ADMIN_IDS:return
    parts=m.text.split(' ',1)
    if len(parts)<2 or '|' not in parts[1]:
        return await m.answer('Usage: /setpay KEY|VALUE\nKeys: upi_id, min_upi, min_usdt, usdt_rate, binance_pay_id, cwallet_id')
    key,value=parts[1].split('|',1); key=key.strip(); value=value.strip()
    allowed={'upi_id','min_upi','min_usdt','usdt_rate','binance_pay_id','cwallet_id'}
    if key not in allowed:return await m.answer('❌ Invalid key.')
    if key in {'min_upi','min_usdt','usdt_rate'}:
        try:value=float(value)
        except:return await m.answer('❌ Numeric value required.')
    await db.settings.update_one({'_id':'payments'},{'$set':{key:value}},upsert=True); await m.answer(f'✅ {key} updated.')

@router.message(Command('setqr'))
async def setqr_cmd(m,state):
    if m.from_user.id not in ADMIN_IDS:return
    await state.set_state(RechargeState.admin_qr); await m.answer('📸 Send the new UPI QR image.')

@router.message(Command('funds'))
async def funds(m,db):
    if m.from_user.id not in ADMIN_IDS:return
    s=await get_settings(db); b=InlineKeyboardBuilder();
    for key,label,ek in [('payments_active','All Payments','payment'),('upi_active','UPI','upi'),('usdt_active','Crypto','crypto')]: b.row(btn(f'{label}: {"ON" if s.get(key,True) else "OFF"}',callback_data=f'fundtoggle:{key}',emoji_key=ek))
    b.row(btn('Payment Settings',callback_data='paysettings',emoji_key='settings')); await m.answer(f'{tag("admin")} <b>Payment Control</b>',parse_mode='HTML',reply_markup=b.as_markup())

@router.callback_query(F.data.startswith('fundtoggle:'))
async def fundtoggle(cq,db):
    if cq.from_user.id not in ADMIN_IDS:return await cq.answer('Denied',show_alert=True)
    key=cq.data.split(':',1)[1]; s=await get_settings(db); await db.settings.update_one({'_id':'payments'},{'$set':{key:not s.get(key,True)}}); await cq.answer('Updated'); await funds(cq.message,db)

@router.callback_query(F.data=='paysettings')
async def paysettings(cq):
    if cq.from_user.id not in ADMIN_IDS:return await cq.answer('Denied',show_alert=True)
    b=InlineKeyboardBuilder()
    for key in ['upi_id','min_upi','min_usdt','usdt_rate','binance_pay_id','cwallet_id']:
        b.button(text=key,callback_data=f'payedit:{key}', icon_custom_emoji_id=__import__('utils.premium_emoji', fromlist=['emoji_id']).emoji_id('edit'))
    b.button(text='Set UPI QR',callback_data='payqr', icon_custom_emoji_id=__import__('utils.premium_emoji', fromlist=['emoji_id']).emoji_id('qr')); b.adjust(2,2,2,1); await cq.message.edit_text('⚙️ <b>Payment Settings</b>',parse_mode='HTML',reply_markup=b.as_markup())

@router.callback_query(F.data.startswith('payedit:'))
async def payedit(cq,state):
    if cq.from_user.id not in ADMIN_IDS:return await cq.answer('Denied',show_alert=True)
    key=cq.data.split(':',1)[1]; await state.update_data(key=key); await cq.message.edit_text(f'✏️ Send new value for <code>{key}</code>:',parse_mode='HTML'); await state.set_state(RechargeState.admin_value)

@router.message(RechargeState.admin_value)
async def payedit_value(m,state,db):
    if m.from_user.id not in ADMIN_IDS:return
    d=await state.get_data(); key=d['key']; value=m.text.strip()
    if key in ('min_upi','min_usdt','usdt_rate'):
        try:value=float(value)
        except:return await m.answer('❌ Enter a number.')
    await db.settings.update_one({'_id':'payments'},{'$set':{key:value}},upsert=True); await state.clear(); await m.answer(f'✅ {key} updated.')

@router.callback_query(F.data=='payqr')
async def payqr(cq,state):
    if cq.from_user.id not in ADMIN_IDS:return await cq.answer('Denied',show_alert=True)
    await cq.message.edit_text('📸 Send the new UPI QR image now.'); await state.set_state(RechargeState.admin_qr)

@router.message(RechargeState.admin_qr,F.photo)
async def payqr_save(m,state,db):
    if m.from_user.id not in ADMIN_IDS:return
    await db.settings.update_one({'_id':'payments'},{'$set':{'upi_qr_file_id':m.photo[-1].file_id}},upsert=True); await state.clear(); await m.answer('✅ UPI QR updated.')
