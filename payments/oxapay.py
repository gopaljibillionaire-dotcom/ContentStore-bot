"""Async OxaPay v1 invoice integration.

Secrets are read from OXAPAY_MERCHANT_API_KEY in .env.
"""
import os
import aiohttp

CREATE_URL = "https://api.oxapay.com/v1/payment/invoice"
STATUS_URL = "https://api.oxapay.com/v1/payment"


def _key():
    return os.getenv("OXAPAY_MERCHANT_API_KEY", "").strip()


async def create_invoice(amount_usd: float, order_id: str):
    key = _key()
    if not key:
        return {"success": False, "error": "OxaPay merchant API key is not configured."}

    payload = {
        "amount": float(amount_usd),
        "currency": "USD",
        "to_currency": "USDT",
        "lifetime": int(os.getenv("OXAPAY_LIFETIME", "30")),
        "fee_paid_by_payer": 1,
        "under_paid_coverage": 2.5,
        "auto_withdrawal": False,
        "mixed_payment": True,
        "order_id": order_id,
        "description": f"Recharge {order_id}",
        "sandbox": os.getenv("OXAPAY_SANDBOX", "false").lower() == "true",
    }
    headers = {"merchant_api_key": key, "Content-Type": "application/json"}

    try:
        timeout = aiohttp.ClientTimeout(total=20, connect=8)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(CREATE_URL, json=payload, headers=headers) as response:
                data = await response.json(content_type=None)
        if data.get("status") == 200 or data.get("message") == "Operation completed successfully!":
            body = data.get("data") or {}
            return {"success": True, "data": body, "raw": data}
        return {"success": False, "error": data.get("message", "OxaPay invoice creation failed"), "raw": data}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


async def check_invoice(track_id: str):
    key = _key()
    if not key:
        return {"status": 500, "message": "OxaPay merchant API key is not configured."}
    url = f"{STATUS_URL}/{track_id}"
    headers = {"merchant_api_key": key, "Content-Type": "application/json"}
    try:
        timeout = aiohttp.ClientTimeout(total=15, connect=8)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers) as response:
                return await response.json(content_type=None)
    except Exception as exc:
        return {"status": 500, "message": str(exc)}


def status_from_response(response):
    """Return normalized status from the different response shapes OxaPay may use."""
    data = response.get("data") if isinstance(response, dict) else None
    if not isinstance(data, dict):
        data = response if isinstance(response, dict) else {}
    return str(data.get("status") or response.get("status") or "").strip().lower()
