##========== created by VTH NETWORK , OWNER : @VALRIK / https://t.me/valriks

import asyncio
from aiogram import Bot,Dispatcher
from config import BOT_TOKEN
from database.db import DB
from handlers.start import router as start_router
from handlers.shop import router as shop_router
from handlers.common import router as common_router
from handlers.admin import router as admin_router
from payments.recharge import router as recharge_router, oxapay_reconciliation_loop
from services.logging_service import log_admin
async def main():
 if not BOT_TOKEN or BOT_TOKEN=='PUT_BOT_TOKEN_HERE': raise RuntimeError('Set BOT_TOKEN in .env')
 bot=Bot(BOT_TOKEN); db=DB(); await db.indexes(); dp=Dispatcher();
 # Make db/bot available to handlers through dispatcher workflow data.
 dp['db']=db; dp['bot']=bot
 dp.include_router(start_router); dp.include_router(common_router); dp.include_router(shop_router); dp.include_router(recharge_router); dp.include_router(admin_router)
 async def on_error(event):
  try:
   await log_admin(bot, f"🚨 <b>BOT ERROR</b>\n\n<code>{type(event.exception).__name__}: {str(event.exception)[:1500]}</code>")
  except Exception: pass
 dp.errors.register(on_error)
 recon_task=asyncio.create_task(oxapay_reconciliation_loop(db, bot))
 try: await dp.start_polling(bot, db=db)
 finally:
  recon_task.cancel()
  try: await recon_task
  except asyncio.CancelledError: pass
  await bot.session.close(); db.client.close()
if __name__=='__main__': asyncio.run(main())
