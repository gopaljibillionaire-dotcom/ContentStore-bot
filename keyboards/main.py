from aiogram.utils.keyboard import InlineKeyboardBuilder
from utils.buttons import btn
from locales.i18n import T

def home_kb(lang='en'):
    x=T.get(lang,T['en']); b=InlineKeyboardBuilder()
    rows=[[(x['products'],'products','products')],[(x['wallet'],'wallet','wallet'),(x['profile'],'profile','profile')],[(x['reviews'],'reviews','reviews'),(x['refer'],'refer','refer')],[(x['support'],'support','support'),(x['sell'],'sell','sell')],[(x['language'],'language','language')]]
    for row in rows: b.row(*(btn(t,callback_data=d,emoji_key=e) for t,d,e in row))
    return b.as_markup()
