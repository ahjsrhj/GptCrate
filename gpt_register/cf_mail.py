import hashlib
import random
import re
import string
import time
from typing import Any, Optional, Set

from curl_cffi import requests

from . import context as ctx
from .ui import rich_print as print


def generate_email() -> tuple[str, str]:
    if not ctx.MAIL_DOMAIN or "." not in ctx.MAIL_DOMAIN:
        print("[Error] MAIL_DOMAIN 未配置或格式不正确")
        return "", ""
    prefix = "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
    email = f"{prefix}@{ctx.MAIL_DOMAIN}"
    return email, email


def extract_otp_code(content: str) -> str:
    if not content:
        return ""

    patterns = [
        r"Your ChatGPT code is\s*(\d{6})",
        r"ChatGPT code is\s*(\d{6})",
        r"verification code to continue:\s*(\d{6})",
        r"Subject:.*?(\d{6})",
    ]
    for pattern in patterns:
        match = re.search(pattern, content, re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1)

    fallback = re.search(r"(?<!\d)(\d{6})(?!\d)", content)
    return fallback.group(1) if fallback else ""


def _response_json(response: Any) -> Any:
    try:
        return response.json()
    except Exception:
        return {}


def _extract_error_text(response: Any, payload: Any) -> str:
    if isinstance(payload, dict):
        for key in ("error", "message", "msg"):
            value = payload.get(key)
            if value:
                return str(value)
        detail = payload.get("detail")
        if isinstance(detail, str) and detail:
            return detail
        if isinstance(detail, dict):
            for key in ("message", "error", "msg"):
                value = detail.get(key)
                if value:
                    return str(value)
    return (getattr(response, "text", "") or "").strip()[:200]


def _extract_mail_list(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]

    if not isinstance(payload, dict):
        return []

    candidates = [
        payload.get("results"),
        payload.get("mails"),
        payload.get("items"),
    ]
    data = payload.get("data")
    if isinstance(data, dict):
        candidates.extend([data.get("results"), data.get("mails"), data.get("items")])
    elif isinstance(data, list):
        candidates.append(data)

    for candidate in candidates:
        if isinstance(candidate, list):
            return [item for item in candidate if isinstance(item, dict)]
    return []


def _mail_id(mail: dict) -> str:
    raw_id = mail.get("id") or mail.get("_id") or mail.get("mail_id") or mail.get("message_id")
    if raw_id:
        return str(raw_id)
    content = "\n".join(
        str(mail.get(key) or "")
        for key in ("subject", "raw", "text", "html", "body", "content")
    )
    return hashlib.sha1(content.encode("utf-8", errors="ignore")).hexdigest()


def _mail_content(mail: dict) -> str:
    parts = [
        str(mail.get("subject") or "").strip(),
        str(mail.get("raw") or "").strip(),
        str(mail.get("text") or mail.get("textBody") or "").strip(),
        str(mail.get("html") or mail.get("htmlBody") or "").strip(),
        str(mail.get("body") or mail.get("content") or "").strip(),
    ]
    return "\n".join(part for part in parts if part)


def _fetch_mails(email: str, headers: dict, proxies: Any = None, limit: int = 5, offset: int = 0) -> tuple[list[dict], str]:
    if not ctx.MAIL_WORKER_BASE:
        return [], "MAIL_WORKER_BASE 未配置"
    if not ctx.MAIL_ADMIN_PASSWORD:
        return [], "MAIL_ADMIN_PASSWORD 未配置"

    params_candidates = [
        {"limit": limit, "offset": offset, "address": email},
        {"limit": limit, "offset": offset, "email": email},
    ]
    seen_param_sets = set()
    last_error = ""

    for params in params_candidates:
        marker = tuple(sorted(params.items()))
        if marker in seen_param_sets:
            continue
        seen_param_sets.add(marker)
        try:
            response = requests.get(
                f"{ctx.MAIL_WORKER_BASE}/admin/mails",
                params=params,
                headers=headers,
                proxies=proxies,
                impersonate="safari",
                verify=ctx._ssl_verify(),
                timeout=15,
            )
            payload = _response_json(response)
            if response.status_code == 200:
                return _extract_mail_list(payload), ""
            last_error = _extract_error_text(response, payload) or f"HTTP {response.status_code}"
        except Exception as exc:
            last_error = str(exc)

    return [], last_error


def get_oai_code(email: str, proxies: Any = None, seen_ids: Optional[Set[str]] = None) -> str:
    headers = {
        "x-admin-auth": ctx.MAIL_ADMIN_PASSWORD,
        "Content-Type": "application/json",
    }
    seen_ids = seen_ids or set()
    last_api_error = ""
    print(f"[*] 正在等待邮箱 {email} 的验证码...", end="", flush=True)

    for _ in range(40):
        print(".", end="", flush=True)
        try:
            results, api_error = _fetch_mails(email=email, headers=headers, proxies=proxies, limit=5, offset=0)
            if api_error and api_error != last_api_error:
                last_api_error = api_error
                print(f"\n[Warning] 邮件 API 返回异常: {api_error}", end="", flush=True)

            for mail in results:
                mail_id = _mail_id(mail)
                if mail_id in seen_ids:
                    continue
                seen_ids.add(mail_id)
                code = extract_otp_code(_mail_content(mail))
                if code:
                    print(" 抓到啦! 验证码:", code)
                    return code
        except Exception as exc:
            if str(exc) != last_api_error:
                last_api_error = str(exc)
                print(f"\n[Warning] 邮件轮询异常: {exc}", end="", flush=True)

        time.sleep(3)

    print(" 超时，未收到验证码")
    return ""


def delete_temp_email(email: str, proxies: Any = None) -> None:
    headers = {
        "x-admin-auth": ctx.MAIL_ADMIN_PASSWORD,
        "Content-Type": "application/json",
    }
    try:
        results, api_error = _fetch_mails(email=email, headers=headers, proxies=proxies, limit=50, offset=0)
        if api_error:
            print(f"[*] 清理临时邮箱时 API 返回: {api_error}")
        for mail in results:
            mail_id = _mail_id(mail)
            if mail_id:
                requests.delete(
                    f"{ctx.MAIL_WORKER_BASE}/admin/mails/{mail_id}",
                    headers=headers,
                    proxies=proxies,
                    impersonate="safari",
                    verify=ctx._ssl_verify(),
                    timeout=10,
                )
        print(f"[*] 临时邮箱 {email} 的邮件已清理")
    except Exception as exc:
        print(f"[*] 清理临时邮箱时出错: {exc}")
