from __future__ import annotations

import time
from typing import Any, Optional

from curl_cffi import requests

from . import context as ctx


def upload_account(token_data: dict[str, Any], proxy_str: Optional[str] = None) -> dict[str, Any]:
    """将新注册账号同步到 Codex2Api，始终直连请求，失败时返回结果而不抛异常。"""
    base_url = (ctx.CODEX2API_BASE_URL or "").strip().rstrip("/")
    admin_secret = (ctx.CODEX2API_ADMIN_SECRET or "").strip()
    refresh_token = str(token_data.get("refresh_token") or "").strip()
    email = str(token_data.get("email") or "").strip()

    if not base_url or not admin_secret:
        return {"attempted": False, "ok": False, "reason": "disabled"}
    if not refresh_token:
        return {"attempted": False, "ok": False, "reason": "missing_refresh_token"}

    url = f"{base_url}/api/admin/accounts"
    payload = {
        "name": email,
        "refresh_token": refresh_token,
        "proxy_url": proxy_str or "",
    }
    headers = {
        "X-Admin-Key": admin_secret,
        "Content-Type": "application/json",
    }
    last_error = "unknown_error"

    for attempt in range(3):
        try:
            response = requests.post(
                url,
                headers=headers,
                json=payload,
                verify=ctx._ssl_verify(),
                timeout=15,
                impersonate="safari",
            )
            if response.status_code in {200, 201}:
                try:
                    data = response.json()
                except Exception:
                    data = {}
                return {
                    "attempted": True,
                    "ok": True,
                    "message": str(data.get("message") or "ok"),
                }
            last_error = f"HTTP {response.status_code}: {response.text[:200]}"
        except Exception as exc:
            last_error = str(exc)

        if attempt < 2:
            time.sleep(2 * (attempt + 1))

    return {"attempted": True, "ok": False, "reason": last_error}
