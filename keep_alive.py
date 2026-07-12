import os
import asyncio
from threading import Thread

from flask import Flask, request, jsonify

app = Flask('')

# Bot được gắn vào ở keep_alive(bot) để endpoint webhook Phase 3 gọi coroutine qua event loop của bot.
_bot = None

# Secret bắt buộc để bảo vệ /mint-invite. Apps Script gửi kèm header X-HVHN-Secret.
MINT_SECRET = os.getenv("HVHN_MINT_SECRET", "").strip()
MINT_TIMEOUT = int(os.getenv("HVHN_MINT_TIMEOUT", "30"))


@app.route('/')
def home():
    return "HVHN Bot đang hoạt động!"


@app.route('/mint-invite', methods=['POST'])
def mint_invite():
    """Phase 3 (Cách A): Apps Script gọi sau khi đối soát chuyển khoản.

    Body JSON: {order_code, name, email, duration_days}. Header: X-HVHN-Secret.
    Trả {invite_url, order_code, reused, ...}. Idempotent theo order_code (chống double-credit).
    """
    if not MINT_SECRET:
        return jsonify({"error": "mint_disabled", "detail": "HVHN_MINT_SECRET chưa được cấu hình"}), 503
    if request.headers.get("X-HVHN-Secret", "").strip() != MINT_SECRET:
        return jsonify({"error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    order_code = str(data.get("order_code") or "").strip()
    name = str(data.get("name") or "").strip()
    email = str(data.get("email") or "").strip().lower()
    try:
        days = int(data.get("duration_days") or 0)
    except (TypeError, ValueError):
        days = 0
    if not order_code or not email or days <= 0:
        return jsonify({"error": "missing_fields", "detail": "Cần order_code, email, duration_days > 0"}), 400

    bot = _bot
    cog = bot.get_cog("Membership") if bot is not None else None
    loop = getattr(bot, "loop", None) if bot is not None else None
    if cog is None or loop is None or not loop.is_running():
        return jsonify({"error": "bot_not_ready"}), 503

    try:
        fut = asyncio.run_coroutine_threadsafe(
            cog.mint_invite_for_order(order_code, name, email, days), loop
        )
        result = fut.result(timeout=MINT_TIMEOUT)
    except ValueError as exc:
        return jsonify({"error": "invalid_input", "detail": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001 — trả lỗi gọn cho Apps Script, log chi tiết ở bot
        print(f"[debug] mint_invite_failed order={order_code} err={type(exc).__name__}: {exc}", flush=True)
        return jsonify({"error": "mint_failed", "detail": type(exc).__name__}), 500

    return jsonify(result), 200


def run():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)


def keep_alive(bot=None):
    global _bot
    _bot = bot
    t = Thread(target=run, daemon=True)
    t.start()
