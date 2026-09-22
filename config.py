import os
from dotenv import load_dotenv

load_dotenv()


def ids(value: str):
    return [int(x.strip()) for x in value.split(',') if x.strip()]


BOT_TOKEN = os.getenv('BOT_TOKEN', '')
MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017')
DB_NAME = os.getenv('DB_NAME', 'content_selling_bot')
ADMIN_IDS = ids(os.getenv('ADMIN_IDS', ''))
SUPPORT_USERNAME = os.getenv('SUPPORT_USERNAME', '@support')
OWNER_USERNAME = os.getenv('OWNER_USERNAME', SUPPORT_USERNAME)
GUIDE_URL = os.getenv('GUIDE_URL', f'https://t.me/{SUPPORT_USERNAME.lstrip("@")}')
REVIEWS_URL = os.getenv('REVIEWS_URL', 'https://t.me/')
SELL_SUPPORT_USERNAME = os.getenv('SELL_SUPPORT_USERNAME', SUPPORT_USERNAME)
#LOGS_CHANNEL_ID = int(os.getenv('LOGS_CHANNEL_ID', '0'))
#ADMIN_LOGS_CHAT_ID = int(os.getenv('ADMIN_LOGS_CHAT_ID', '0'))
#FORCE_JOIN_1 = os.getenv('FORCE_JOIN_1', '')
#FORCE_JOIN_2 = os.getenv('FORCE_JOIN_2', '')
BOT_USERNAME = os.getenv('BOT_USERNAME', '')
