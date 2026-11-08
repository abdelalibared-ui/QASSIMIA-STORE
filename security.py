
import hashlib
import hmac
import json
import os
import time
from urllib.parse import parse_qsl

def verify_telegram_init_data(init_data: str, bot_token: str, max_age_seconds: int = 86400):
    """Validate Telegram Mini App initData using Telegram's documented HMAC procedure."""
    if not init_data or not bot_token:
        return None
    try:
        data = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = data.pop("hash", None)
        if not received_hash:
            return None
        auth_date = int(data.get("auth_date", "0"))
        if auth_date <= 0 or time.time() - auth_date > max_age_seconds:
            return None
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
        secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        calculated = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calculated, received_hash):
            return None
        user = json.loads(data.get("user", "{}"))
        return user if isinstance(user, dict) else None
    except Exception:
        return None

def require_admin(request):
    from fastapi import HTTPException
    import secrets
    expected_user = os.getenv("ADMIN_USERNAME", "admin")
    expected_pass = os.getenv("ADMIN_PASSWORD", "")
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Basic ") or not expected_pass:
        raise HTTPException(status_code=401, detail="Authentication required",
                            headers={"WWW-Authenticate": "Basic"})
    import base64
    try:
        decoded = base64.b64decode(auth.split(" ", 1)[1]).decode()
        username, password = decoded.split(":", 1)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not (secrets.compare_digest(username, expected_user) and secrets.compare_digest(password, expected_pass)):
        raise HTTPException(status_code=401, detail="Invalid credentials")
