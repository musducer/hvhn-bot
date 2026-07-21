import os
import asyncio
import hmac
import re
import time
from collections import deque
from concurrent.futures import TimeoutError as FutureTimeoutError
from threading import Lock, Thread

from flask import Flask, request, jsonify
from env_utils import env_int

app = Flask('')
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024

# Bot được gắn vào ở keep_alive(bot) để endpoint webhook Phase 3 gọi coroutine qua event loop của bot.
_bot = None

# Secret bắt buộc để bảo vệ /mint-invite. Apps Script gửi kèm header X-HVHN-Secret.
MINT_SECRET = os.getenv("HVHN_MINT_SECRET", "").strip()
MINT_TIMEOUT = env_int("HVHN_MINT_TIMEOUT", 30, minimum=5, maximum=120)
MINT_RATE_LIMIT = env_int("HVHN_MINT_RATE_LIMIT", 24, minimum=1, maximum=240)
MINT_RATE_WINDOW_SECONDS = env_int("HVHN_MINT_RATE_WINDOW_SECONDS", 60, minimum=10, maximum=3600)
_mint_attempts: deque[float] = deque()
_mint_attempts_lock = Lock()


def _allow_mint_attempt() -> bool:
    """Bound authenticated invite creation so a leaked integration secret has limited blast radius."""
    now = time.monotonic()
    with _mint_attempts_lock:
        while _mint_attempts and now - _mint_attempts[0] >= MINT_RATE_WINDOW_SECONDS:
            _mint_attempts.popleft()
        if len(_mint_attempts) >= MINT_RATE_LIMIT:
            return False
        _mint_attempts.append(now)
        return True


def _valid_name(value: str) -> bool:
    return bool(
        value
        and len(value) <= 120
        and not re.search(r"[\x00-\x1f\x7f]", value)
        and not value.startswith(("=", "+", "-", "@"))
    )


def _valid_order_code(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_-]{3,128}", value))


@app.errorhandler(413)
def payload_too_large(_error):
    return jsonify({"error": "payload_too_large"}), 413


@app.after_request
def security_headers(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


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
    supplied_secret = request.headers.get("X-HVHN-Secret", "").strip()
    if not hmac.compare_digest(supplied_secret.encode("utf-8"), MINT_SECRET.encode("utf-8")):
        return jsonify({"error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"error": "invalid_json"}), 400
    order_code = str(data.get("order_code") or "").strip()
    name = str(data.get("name") or "").strip()
    email = str(data.get("email") or "").strip().lower()
    try:
        days = int(data.get("duration_days") or 0)
    except (TypeError, ValueError):
        days = 0
    if not order_code or not name or not email or days <= 0:
        return jsonify({"error": "missing_fields", "detail": "Cần order_code, name, email, duration_days > 0"}), 400
    if (not _valid_order_code(order_code) or not _valid_name(name)
            or len(email) > 320 or days > 366
            or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email)):
        return jsonify({"error": "invalid_input"}), 400
    if not _allow_mint_attempt():
        return jsonify({"error": "rate_limited"}), 429

    bot = _bot
    cog = bot.get_cog("Membership") if bot is not None else None
    loop = getattr(bot, "loop", None) if bot is not None else None
    if cog is None or loop is None or not loop.is_running():
        return jsonify({"error": "bot_not_ready"}), 503

    fut = None
    try:
        fut = asyncio.run_coroutine_threadsafe(
            cog.mint_invite_for_order(order_code, name, email, days), loop
        )
        result = fut.result(timeout=MINT_TIMEOUT)
    except FutureTimeoutError:
        if fut is not None:
            fut.cancel()
        print(f"[debug] mint_invite_timeout order={order_code} timeout={MINT_TIMEOUT}", flush=True)
        return jsonify({"error": "mint_timeout"}), 504
    except ValueError as exc:
        return jsonify({"error": "invalid_input", "detail": str(exc)}), 400
    except Exception as exc:  # Trả lỗi gọn cho Apps Script; bot vẫn ghi chi tiết.
        print(f"[debug] mint_invite_failed order={order_code} err={type(exc).__name__}: {exc}", flush=True)
        return jsonify({"error": "mint_failed", "detail": type(exc).__name__}), 500

    return jsonify(result), 200


def run():
    port = env_int("PORT", 8080, minimum=1, maximum=65535)
    # Render exposes this process through its own proxy, so binding all interfaces is required.
    app.run(host='0.0.0.0', port=port, threaded=True)  # nosec B104


def keep_alive(bot=None):
    global _bot
    _bot = bot
    t = Thread(target=run, daemon=True)
    t.start()
