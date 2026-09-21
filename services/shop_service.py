from datetime import datetime,timezone
from bson import ObjectId
async def categories(db): return await db.categories.find({'active':True}).sort('order',1).to_list(None)
async def subs(db,cat): return await db.subcategories.find({'category_id':ObjectId(cat),'active':True}).sort('order',1).to_list(None)
async def products(db,cat=None,sub=None):
    q={'active':True}
    if cat:q['category_id']=ObjectId(cat)
    if sub:q['subcategory_id']=ObjectId(sub)
    return await db.products.find(q).sort('order',1).to_list(None)
async def product(db,pid): return await db.products.find_one({'_id':ObjectId(pid),'active':True})
async def search_products(db,q): return await db.products.find({'active':True,'name':{'$regex':q,'$options':'i'}}).limit(30).to_list(None)
async def create_order(db,user,p,qty,total):
    now=datetime.now(timezone.utc)
    order={'user_id':user,'product_id':p['_id'],'product_name':p['name'],'unit_price':p['price'],'quantity':qty,'total':total,'status':'paid','created_at':now}
    r=await db.orders.insert_one(order); return r.inserted_id
