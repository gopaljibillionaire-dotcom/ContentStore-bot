from html import escape
from utils.premium_emoji import tag
from locales.i18n import T

def price(v): return f'₹{float(v):,.2f}'.rstrip('0').rstrip('.')
def product_list(products, lang='en'):
    x=T.get(lang,T['en'])
    if not products: return x['no_products']
    lines=[f"{tag('products')} <b>{x['available']}</b>"]
    for p in products:
        stock=p.get('stock',0); stock_text=x['unlimited'] if stock is None else str(stock)
        lines.append(f"• <b>{escape(p['name'])}</b> — {price(p['price'])} · {x['stock']}: {stock_text}")
    return '\n'.join(lines)
