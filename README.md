# Content Selling Bot — Clean UI Upgrade

This build upgrades the supplied project with:

- Interactive admin management: no category/product IDs required in normal commands.
- `/addproduct` → choose category → sub-category → enter name → price → stock.
- `/editcat`, `/delcat`, `/editsub`, `/delsub`, `/editproduct`, `/delproduct`, `/stock` open guided menus.
- Interactive user balance, ban/unban and lookup tools.
- Cleaner category → sub-category → product navigation.
- Live product/price/stock list remains above product buttons.
- User custom quantity/search flows reuse the existing bot message where possible and delete the user's input.
- Manual UPI and manual crypto flows reuse the existing payment message where Telegram permits instead of stacking prompts.
- Premium custom emoji support uses Telegram's `icon_custom_emoji_id` field.
- Updated aiogram to 3.30.0 (Bot API 9.5-era support).
- Fixed duplicate `bot` keyword in `start_polling`.
- Added missing force-join callback handlers.
- Existing payment integrations, referral logic, two force-join channels, broadcast, languages and database structure are retained.

## Premium emoji

Edit `utils/premium_emoji.py` and put your real custom emoji IDs into `PREMIUM_IDS`.

Example:
`'home': '5909174430000484676'`

Telegram requires Bot API 9.4+ and the bot must be eligible to use custom emoji. If the bot is not eligible or an ID is invalid, the Unicode fallback is used.

## Install

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python bot.py
```

Keep `.env` out of Git and do not publish payment/API secrets.

### OxaPay Auto Crypto
Set `OXAPAY_MERCHANT_API_KEY` in `.env`. The bot uses OxaPay v1 invoice creation and status lookup, stores the `track_id`, and runs a background reconciliation loop (default every 15 seconds) so successful payments are credited without requiring the user to repeatedly press a button. A manual **Check Payment** button remains as a fallback.

The integration is asynchronous and does not block Telegram callback handlers. OxaPay's current invoice flow uses `POST /v1/payment/invoice` and status reconciliation by `GET /v1/payment/{track_id}`. urlOxaPay API documentationhttps://oxapay.com/

## UI/Navigation updates
- Home-screen feature pages (Profile, Wallet, Refer, Reviews, Support, Sell, Language) edit the same message and use a single Back-to-Home button.
- Product navigation preserves hierarchy: Product -> Sub-category -> Category -> Home.
- The sub-category page shows only sub-category buttons; the live product/rate list appears only after opening a sub-category.
- Categories, sub-categories, and products can store their own Telegram custom-emoji ID for their buttons. Admins are prompted to send the premium emoji during creation.
- Product creation flow: name -> premium emoji -> price -> description -> link/file -> Unlimited or Single.
- Product descriptions retain Telegram rich formatting/custom emoji entities by storing Telegram HTML representation.

## Final UI fixes in this build
- Premium button icons are now mutually exclusive with their Unicode fallback: a button shows either the configured premium icon or the normal emoji, never both.
- This rule is applied to admin, shop, navigation and language buttons.
- Sub-category photo pages now use the actual sub-category name and saved premium emoji in the caption.
- Product buttons on photo sub-category pages now work because the bot edits the photo caption instead of trying to convert the photo message into text.
- Back navigation preserves the category/sub-category hierarchy, including products without a sub-category.
- Search and product/category actions show lightweight loading/processing feedback.
- Refer & Earn now shows the live reward rate, successful referrals, total earned and the referral process.
- Support now has Guide, Owner, Report Problem and Back actions.
- Support reports accept text, photos and photos with captions, remove the user's submitted message, show a success confirmation, and send the report plus user details to `ADMIN_LOGS_CHAT_ID`.
- Referral earnings are stored in `referral_earnings` so the total earned value remains available.

### New `.env` settings
- `OWNER_USERNAME=@your_owner`
- `GUIDE_URL=https://t.me/your_guide`
