from motor.motor_asyncio import AsyncIOMotorClient
from config import MONGO_URI,DB_NAME
class DB:
    def __init__(self): self.client=AsyncIOMotorClient(MONGO_URI); self.db=self.client[DB_NAME]
    @property
    def users(self): return self.db.users
    @property
    def categories(self): return self.db.categories
    @property
    def subcategories(self): return self.db.subcategories
    @property
    def products(self): return self.db.products
    @property
    def orders(self): return self.db.orders
    @property
    def transactions(self): return self.db.transactions
    @property
    def reviews(self): return self.db.reviews
    @property
    def settings(self): return self.db.settings
    @property
    def balance_ledger(self): return self.db.balance_ledger
    @property
    def audit_logs(self): return self.db.audit_logs
    @property
    def broadcasts(self): return self.db.broadcasts
    async def indexes(self):
        await self.users.create_index('telegram_id',unique=True)
        await self.products.create_index([('category_id',1),('subcategory_id',1)])
        await self.orders.create_index('user_id')
        await self.transactions.create_index('user_id')
        await self.balance_ledger.create_index([('user_id', 1), ('created_at', -1)])
        await self.audit_logs.create_index([('created_at', -1)])
