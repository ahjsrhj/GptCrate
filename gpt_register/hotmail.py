from __future__ import annotations

import re
import threading
import time
import urllib.parse
from typing import Any

from curl_cffi import requests

from . import context as ctx
from .cf_mail import extract_otp_code
from .microsoft_alias import expand_microsoft_alias_emails
from .ui import rich_print as print

_MAIL_ACCESS_RETRY_LIMIT = 3
_HOTMAIL007_ALIAS_COUNT = 5
_HOTMAIL007_QUEUE_LOCK = threading.Lock()


def _resolve_outlook_mail_mode(preferred: str | None = None) -> str:
    mode = (preferred or "graph").strip().lower()
    return mode if mode in {"graph", "imap"} else "graph"


def _is_timeout_error(error: Any) -> bool:
    text = str(error or "").strip().lower()
    if not text:
        return False
    timeout_markers = [
        "timed out",
        "timeout",
        "curl: (28)",
        "operation timed out",
        "connection timed out",
    ]
    return any(marker in text for marker in timeout_markers)


def _normalize_mail_error(error: Any) -> str:
    return re.sub(r"\s+", " ", str(error or "")).strip()[:180]


def _is_user_cancelled_request_error(error: Any) -> bool:
    text = str(error or "").strip().lower()
    if not text:
        return False
    return "curl: (23)" in text and "failure writing output to destination" in text


def _is_retryable_mail_access_error(reason: Any) -> bool:
    text = str(reason or "").strip().lower()
    if not text:
        return False
    if text.startswith("mail_access_retryable:"):
        return True
    if _is_timeout_error(text):
        return True
    retryable_markers = [
        "http 408",
        "http 429",
        "http 500",
        "http 502",
        "http 503",
        "http 504",
        "http_408",
        "http_429",
        "http_500",
        "http_502",
        "http_503",
        "http_504",
        "service unavailable",
        "temporarily unavailable",
        "too many requests",
        "connection reset",
        "connection refused",
        "network is unreachable",
    ]
    return any(marker in text for marker in retryable_markers)


def _local_outlook_account_to_line(account: dict) -> str:
    return "----".join(
        [
            str(account.get("email") or "").strip(),
            str(account.get("password") or "").strip(),
            str(account.get("client_id") or "").strip(),
            str(account.get("refresh_token") or "").strip(),
        ]
    )


def _record_local_outlook_bad_account(account: dict, reason: str) -> None:
    import os

    reason_text = str(reason or "unknown").replace("\n", " ").strip()
    line = _local_outlook_account_to_line(account)
    if not line:
        return
    bad_file = ctx.LOCAL_OUTLOOK_BAD_FILE or "bad_local_outlook.txt"
    bad_dir = os.path.dirname(bad_file)
    if bad_dir:
        os.makedirs(bad_dir, exist_ok=True)
    with ctx._file_write_lock:
        with open(bad_file, "a", encoding="utf-8") as handle:
            handle.write(f"{line} # {reason_text}\n")
    print(f"[*] 已记录坏号到 {bad_file}: {account.get('email')} ({reason_text[:120]})")


def _should_record_local_outlook_bad_account(reason: str) -> bool:
    text = str(reason or "").strip().lower()
    if not text:
        return False
    transient_markers = [
        "mail_access_retryable:",
        "could not resolve host",
        "failed to perform",
        "timed out",
        "timeout",
        "http 408",
        "http 429",
        "http 500",
        "http 502",
        "http 503",
        "http 504",
        "proxy",
        "connection reset",
        "connection refused",
        "temporarily unavailable",
        "network is unreachable",
        "ssl",
        "tls",
    ]
    if any(marker in text for marker in transient_markers):
        return False
    bad_markers = [
        "invalid_grant",
        "invalid_client",
        "unauthorized_client",
        "invalid refresh token",
        "token_error:",
        "账号被封禁",
        "service abuse",
        "consent_required",
        "interaction_required",
        "imap 所有方法均失败",
    ]
    return any(marker in text for marker in bad_markers)


def _set_mail_error(email_addr: str, reason: str | None) -> None:
    creds = ctx._hotmail007_credentials.get(email_addr)
    if creds is None:
        return
    if reason:
        creds["last_mail_error"] = reason
    else:
        creds.pop("last_mail_error", None)


def get_last_mail_error(email_addr: str) -> str:
    creds = ctx._hotmail007_credentials.get(email_addr, {})
    return str(creds.get("last_mail_error") or "").strip()


def is_retryable_mail_error(reason: Any) -> bool:
    return _is_retryable_mail_access_error(reason)


def _hotmail007_api_get(path: str, proxies: Any = None, **params) -> dict:
    url = f"{ctx.HOTMAIL007_API_URL}/{path.lstrip('/')}"
    if params:
        qs = "&".join(
            f"{key}={urllib.parse.quote(str(value))}" for key, value in params.items() if value
        )
        url = f"{url}?{qs}"
    resolved_proxies = ctx.resolve_outlook_proxies(proxies)
    try:
        response = requests.get(
            url,
            proxies=resolved_proxies,
            verify=ctx._ssl_verify(),
            timeout=15,
            impersonate="safari",
        )
        return response.json()
    except Exception as exc:
        if _is_user_cancelled_request_error(exc):
            raise KeyboardInterrupt from exc
        return {"success": False, "message": str(exc)[:200]}


def hotmail007_get_balance(proxies: Any = None) -> tuple:
    data = _hotmail007_api_get("api/user/balance", proxies=proxies, clientKey=ctx.HOTMAIL007_API_KEY)
    if data.get("success") and data.get("code") == 0:
        return data.get("data"), None
    return None, data.get("message", "查询余额失败")


def hotmail007_get_stock(proxies: Any = None) -> tuple:
    params = {"clientKey": ctx.HOTMAIL007_API_KEY}
    if ctx.HOTMAIL007_MAIL_TYPE:
        params["mailType"] = ctx.HOTMAIL007_MAIL_TYPE
    data = _hotmail007_api_get("api/mail/getStock", proxies=proxies, **params)
    if data.get("success") and data.get("code") == 0:
        raw = data.get("data")
        if isinstance(raw, (int, float)):
            return int(raw), None
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict):
                    mail_type = (item.get("type") or "").strip().lower()
                    if mail_type == ctx.HOTMAIL007_MAIL_TYPE.strip().lower():
                        return int(item.get("stock", 0)), None
            return sum(int(item.get("stock", 0)) for item in raw if isinstance(item, dict)), None
        return 0, None
    return None, data.get("message", "查询库存失败")


def hotmail007_get_mail(quantity: int = 1, proxies: Any = None) -> tuple:
    data = _hotmail007_api_get(
        "api/mail/getMail",
        proxies=proxies,
        clientKey=ctx.HOTMAIL007_API_KEY,
        mailType=ctx.HOTMAIL007_MAIL_TYPE,
        quantity=quantity,
    )
    if not data.get("success") or data.get("code") != 0:
        return [], data.get("message", "拉取邮箱失败")

    out = []
    for raw in data.get("data") or []:
        if not isinstance(raw, str):
            continue
        parts = raw.split(":")
        if len(parts) < 4:
            continue
        email_addr = parts[0].strip()
        password = parts[1].strip()
        client_id = parts[-1].strip()
        refresh_token = ":".join(parts[2:-1]).strip()
        if email_addr:
            out.append({
                "email": email_addr,
                "password": password,
                "refresh_token": refresh_token,
                "client_id": client_id,
            })
    if not out:
        return [], "API 返回数据解析为空"
    return out, ""


def _get_hotmail007_queue() -> ctx.ActiveEmailQueue:
    if ctx._hotmail007_queue is None:
        ctx._hotmail007_queue = ctx.ActiveEmailQueue()
    return ctx._hotmail007_queue


def _build_hotmail007_queue_accounts(mail_info: dict) -> list[dict]:
    primary_email = str(mail_info.get("email") or "").strip()
    if not primary_email:
        return []

    if ctx.HOTMAIL007_ALIAS_SPLIT_ENABLED:
        email_addresses = expand_microsoft_alias_emails(
            primary_email,
            count=_HOTMAIL007_ALIAS_COUNT,
            include_original=False,
        )
    else:
        email_addresses = [primary_email]

    mail_mode = _resolve_outlook_mail_mode(ctx.HOTMAIL007_MAIL_MODE)
    return [
        {
            "email": email_addr,
            "primary_email": primary_email,
            "password": str(mail_info.get("password") or "").strip(),
            "refresh_token": str(mail_info.get("refresh_token") or "").strip(),
            "client_id": str(mail_info.get("client_id") or "").strip(),
            "mail_mode": mail_mode,
        }
        for email_addr in email_addresses
        if str(email_addr or "").strip()
    ]


def _fetch_hotmail007_account_with_retry(proxies: Any = None) -> dict | None:
    max_retry = max(1, int(getattr(ctx, "HOTMAIL007_MAX_RETRY", 3) or 3))
    buy_retry = 0
    fetch_retry = 0
    while True:
        mails, err = hotmail007_get_mail(quantity=1, proxies=proxies)
        if not err and mails:
            return mails[0]

        print(f"[Error] Hotmail007 拉取邮箱失败: {err}")
        err_text = str(err or "").strip().lower()
        if _is_user_cancelled_request_error(err):
            raise KeyboardInterrupt
        if err_text == "buy error":
            buy_retry += 1
            print(f"[*] Hotmail007 购买邮箱暂时失败，立即重试 (第 {buy_retry} 次)...")
            continue

        fetch_retry += 1
        if fetch_retry > max_retry:
            return None
        print(f"[*] Hotmail007 拉取邮箱失败，立即重试 ({fetch_retry}/{max_retry})...")


def _pop_hotmail007_queue_account(proxies: Any = None) -> tuple[dict | None, int]:
    queue = _get_hotmail007_queue()
    with _HOTMAIL007_QUEUE_LOCK:
        account = queue.pop()
        if account is None:
            print("[*] Hotmail007 队列为空，开始购买新邮箱补货...")
            mail_info = _fetch_hotmail007_account_with_retry(proxies=proxies)
            if not mail_info:
                return None, 0

            queue_accounts = _build_hotmail007_queue_accounts(mail_info)
            if not queue_accounts:
                return None, 0
            queue.add_batch(queue_accounts)

            if ctx.HOTMAIL007_ALIAS_SPLIT_ENABLED:
                print(
                    f"[*] Hotmail007 购买成功，已将 {mail_info['email']} 裂变为 "
                    f"{len(queue_accounts)} 个别名并加入队列"
                )
            else:
                print(f"[*] Hotmail007 购买成功，已将 {mail_info['email']} 加入队列")

            account = queue.pop()
        remaining = len(queue)
    return account, remaining


def _outlook_get_graph_token(client_id: str, refresh_token: str, proxies: Any = None) -> str:
    resolved_proxies = ctx.resolve_outlook_proxies(proxies)
    response = requests.post(
        "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        data={
            "client_id": client_id,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "scope": "https://graph.microsoft.com/.default",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        proxies=resolved_proxies,
        verify=ctx._ssl_verify(),
        timeout=30,
        impersonate="safari",
    )
    payload = response.json()
    if not payload.get("access_token"):
        error = payload.get("error_description", payload.get("error", str(payload)))
        if "service abuse" in (error or "").lower():
            raise Exception(f"账号被封禁: {error}")
        raise Exception(f"Graph token 失败: {error[:150]}")
    return payload["access_token"]


def _outlook_get_imap_token(client_id: str, refresh_token: str, proxies: Any = None, email_addr: str = "") -> tuple:
    import imaplib as _imaplib

    resolved_proxies = ctx.resolve_outlook_proxies(proxies)
    methods = [
        {
            "url": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
            "data": {
                "client_id": client_id, "grant_type": "refresh_token", "refresh_token": refresh_token,
                "scope": "https://outlook.office365.com/IMAP.AccessAsUser.All offline_access",
            },
            "imap_server": "outlook.office365.com",
        },
        {
            "url": "https://login.microsoftonline.com/consumers/oauth2/v2.0/token",
            "data": {
                "client_id": client_id, "grant_type": "refresh_token", "refresh_token": refresh_token,
                "scope": "https://outlook.office365.com/IMAP.AccessAsUser.All offline_access",
            },
            "imap_server": "outlook.office365.com",
        },
        {
            "url": "https://login.microsoftonline.com/consumers/oauth2/v2.0/token",
            "data": {
                "client_id": client_id, "grant_type": "refresh_token", "refresh_token": refresh_token,
                "scope": "https://outlook.office.com/IMAP.AccessAsUser.All offline_access",
            },
            "imap_server": "outlook.live.com",
        },
        {
            "url": "https://login.live.com/oauth20_token.srf",
            "data": {"client_id": client_id, "grant_type": "refresh_token", "refresh_token": refresh_token},
            "imap_server": "outlook.office365.com",
        },
    ]
    last_err = ""
    for idx, method in enumerate(methods):
        try:
            response = requests.post(
                method["url"],
                data=method["data"],
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                proxies=resolved_proxies,
                verify=ctx._ssl_verify(),
                timeout=30,
                impersonate="safari",
            )
            payload = response.json()
            if not payload.get("access_token"):
                last_err = payload.get("error_description", payload.get("error", str(payload)))
                if "service abuse" in (last_err or "").lower():
                    raise Exception(f"账号被封禁: {last_err}")
                continue
            token = payload["access_token"]
            server = method["imap_server"]
            if email_addr:
                try:
                    imap_test = _imaplib.IMAP4_SSL(server, 993)
                    auth_str = f"user={email_addr}\x01auth=Bearer {token}\x01\x01"
                    imap_test.authenticate("XOAUTH2", lambda _: auth_str.encode("utf-8"))
                    imap_test.select("INBOX")
                    imap_test.logout()
                    print(f"[IMAP] 方法{idx + 1}验证通过: {server}")
                    return token, server
                except Exception as exc:
                    last_err = f"方法{idx + 1} SELECT失败({server}): {exc}"
                    print(f"[IMAP] {last_err}")
                    continue
            else:
                return token, server
        except Exception as exc:
            if "封禁" in str(exc):
                raise
            last_err = str(exc)
    raise Exception(f"IMAP 所有方法均失败: {last_err[:200]}")


def _outlook_graph_get_openai_messages_detailed(
    access_token: str,
    proxies: Any = None,
    top: int = 10,
) -> tuple[list, str, bool]:
    all_items = []
    fetch_errors = []
    had_success_response = False
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    resolved_proxies = ctx.resolve_outlook_proxies(proxies)
    params = {
        "$select": "id,subject,body,from,receivedDateTime",
        "$orderby": "receivedDateTime desc",
        "$top": str(top * 5),
    }
    for folder in ["inbox", "junkemail"]:
        try:
            response = requests.get(
                f"https://graph.microsoft.com/v1.0/me/mailFolders/{folder}/messages",
                params=params,
                headers=headers,
                proxies=resolved_proxies,
                verify=ctx._ssl_verify(),
                timeout=30,
                impersonate="safari",
            )
            if response.status_code == 200:
                had_success_response = True
                all_items.extend(response.json().get("value", []))
            else:
                fetch_errors.append(f"{folder}:HTTP {response.status_code}")
        except Exception as exc:
            fetch_errors.append(f"{folder}:{_normalize_mail_error(exc)}")
    if not all_items:
        try:
            response = requests.get(
                "https://graph.microsoft.com/v1.0/me/messages",
                params=params,
                headers=headers,
                proxies=resolved_proxies,
                verify=ctx._ssl_verify(),
                timeout=30,
                impersonate="safari",
            )
            if response.status_code == 200:
                had_success_response = True
                all_items = response.json().get("value", [])
            else:
                fetch_errors.append(f"all:HTTP {response.status_code}")
        except Exception as exc:
            fetch_errors.append(f"all:{_normalize_mail_error(exc)}")
    unique_errors = []
    for item in fetch_errors:
        if item and item not in unique_errors:
            unique_errors.append(item)
    return [
        item for item in all_items
        if "openai.com" in (item.get("from") or {}).get("emailAddress", {}).get("address", "").lower()
    ], "; ".join(unique_errors[:3]), had_success_response


def _outlook_graph_get_openai_messages(access_token: str, proxies: Any = None, top: int = 10) -> list:
    messages, _, _ = _outlook_graph_get_openai_messages_detailed(access_token, proxies=proxies, top=top)
    return messages


def _outlook_graph_extract_otp(message: dict) -> str:
    subject = message.get("subject", "")
    body_content = (message.get("body") or {}).get("content", "")
    text = subject + "\n" + body_content
    for pattern in [r">\s*(\d{6})\s*<", r"code[:\s]+(\d{6})", r"(\d{6})\s*\n", r"(?<!\d)(\d{6})(?!\d)"]:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1)
    return ""


def _outlook_get_known_ids(email_addr: str, client_id: str, refresh_token: str, proxies: Any = None) -> set:
    try:
        token = _outlook_get_graph_token(client_id, refresh_token, proxies)
        messages = _outlook_graph_get_openai_messages(token, proxies)
        known = {message["id"] for message in messages}
        print(f"[Graph] 已有 {len(known)} 封 OpenAI 邮件")
        return known
    except Exception as exc:
        print(f"[Graph] 获取已有邮件失败: {exc}")
        return set()


def _outlook_fetch_otp_graph(
    email_addr: str,
    client_id: str,
    refresh_token: str,
    known_ids: set,
    proxies: Any = None,
    timeout: int = 120,
    error_email: str | None = None,
) -> str:
    state_email = str(error_email or email_addr).strip() or email_addr
    _set_mail_error(state_email, None)
    try:
        access_token = _outlook_get_graph_token(client_id, refresh_token, proxies)
    except Exception as exc:
        _set_mail_error(state_email, f"token_error:{exc}")
        print(f"[Graph] access token 失败: {exc}")
        return ""

    debug_done = False
    access_retry_count = 0
    last_access_error = ""
    had_successful_mail_fetch = False
    print(f"[Graph] 轮询收件箱(最多{timeout}s, 已知{len(known_ids)}封)...", end="", flush=True)
    start = time.time()
    while time.time() - start < timeout:
        print(".", end="", flush=True)
        try:
            messages, fetch_error, has_success_response = _outlook_graph_get_openai_messages_detailed(access_token, proxies)
            if has_success_response:
                had_successful_mail_fetch = True
                access_retry_count = 0
            elif fetch_error:
                last_access_error = fetch_error
                if _is_retryable_mail_access_error(fetch_error):
                    access_retry_count += 1
                    print(
                        f"\n[Graph] 邮箱访问异常，准备重新访问 ({access_retry_count}/{_MAIL_ACCESS_RETRY_LIMIT}): "
                        f"{fetch_error[:120]}",
                        end="",
                        flush=True,
                    )
                    if access_retry_count >= _MAIL_ACCESS_RETRY_LIMIT:
                        _set_mail_error(state_email, f"mail_access_retryable:{_normalize_mail_error(fetch_error)}")
                        print("\n[Graph] 邮箱访问连续失败，本轮先结束，交给上层重试", end="", flush=True)
                        return ""
                else:
                    access_retry_count = 0
                    print(f"\n[Graph] 邮箱访问异常: {fetch_error[:120]}", end="", flush=True)
            if not debug_done:
                debug_done = True
                headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
                resolved_proxies = ctx.resolve_outlook_proxies(proxies)
                for folder in ["inbox", "junkemail"]:
                    try:
                        debug_response = requests.get(
                            f"https://graph.microsoft.com/v1.0/me/mailFolders/{folder}/messages",
                            params={"$top": "3", "$select": "id,subject,from,receivedDateTime"},
                            headers=headers,
                            proxies=resolved_proxies,
                            verify=ctx._ssl_verify(),
                            timeout=15,
                            impersonate="safari",
                        )
                        if debug_response.status_code == 200:
                            debug_messages = debug_response.json().get("value", [])
                            print(f"\n[Graph调试] {folder}: {len(debug_messages)}封邮件", end="", flush=True)
                            for debug_message in debug_messages[:3]:
                                sender = (debug_message.get("from") or {}).get("emailAddress", {}).get("address", "?")
                                subject = (debug_message.get("subject") or "")[:40]
                                print(f"\n  - from={sender} subj={subject}", end="", flush=True)
                        else:
                            print(f"\n[Graph调试] {folder}: HTTP {debug_response.status_code}", end="", flush=True)
                    except Exception as exc:
                        print(f"\n[Graph调试] {folder}异常: {exc}", end="", flush=True)

            all_ids = {message["id"] for message in messages}
            new_ids = all_ids - known_ids
            for message in [item for item in messages if item["id"] in new_ids]:
                code = _outlook_graph_extract_otp(message)
                if code:
                    print(f" 抓到啦! 验证码: {code}")
                    return code
        except Exception as exc:
            last_access_error = _normalize_mail_error(exc)
            if _is_retryable_mail_access_error(last_access_error):
                access_retry_count += 1
                print(
                    f"\n[Graph] 轮询出错，准备重新访问 ({access_retry_count}/{_MAIL_ACCESS_RETRY_LIMIT}): "
                    f"{last_access_error[:120]}",
                    end="",
                    flush=True,
                )
                if access_retry_count >= _MAIL_ACCESS_RETRY_LIMIT:
                    _set_mail_error(state_email, f"mail_access_retryable:{last_access_error}")
                    print("\n[Graph] 邮箱访问连续失败，本轮先结束，交给上层重试", end="", flush=True)
                    return ""
            else:
                access_retry_count = 0
                print(f"\n[Graph] 轮询出错: {exc}", end="", flush=True)
        time.sleep(3)
    if not had_successful_mail_fetch and last_access_error:
        if _is_retryable_mail_access_error(last_access_error):
            _set_mail_error(state_email, f"mail_access_retryable:{_normalize_mail_error(last_access_error)}")
        else:
            _set_mail_error(state_email, f"mail_access_error:{_normalize_mail_error(last_access_error)}")
    else:
        _set_mail_error(state_email, "otp_timeout")
    print(" 超时，未收到验证码")
    return ""


def _outlook_fetch_otp_imap(email_addr: str, client_id: str, refresh_token: str, known_ids: set, proxies: Any = None, timeout: int = 120, error_email: str | None = None) -> str:
    import email as email_lib
    import imaplib

    state_email = str(error_email or email_addr).strip() or email_addr
    _set_mail_error(state_email, None)
    try:
        access_token, imap_server = _outlook_get_imap_token(client_id, refresh_token, proxies, email_addr=email_addr)
    except Exception as exc:
        _set_mail_error(state_email, f"token_error:{exc}")
        print(f"[IMAP] access token 失败: {exc}")
        return ""

    print(f"[IMAP] 轮询收件箱(最多{timeout}s, 已知{len(known_ids)}封)...", end="", flush=True)
    start = time.time()
    had_successful_mail_fetch = False
    last_access_error = ""
    while time.time() - start < timeout:
        print(".", end="", flush=True)
        try:
            imap = imaplib.IMAP4_SSL(imap_server, 993)
            auth_str = f"user={email_addr}\x01auth=Bearer {access_token}\x01\x01"
            imap.authenticate("XOAUTH2", lambda _: auth_str.encode("utf-8"))
            try:
                imap.select("INBOX")
                had_successful_mail_fetch = True
                status, msg_ids = imap.search(None, '(FROM "noreply@tm.openai.com")')
                if status != "OK" or not msg_ids[0]:
                    status, msg_ids = imap.search(None, '(FROM "openai.com")')
                if status == "OK" and msg_ids[0]:
                    all_ids = set(msg_ids[0].split())
                    new_ids = all_ids - known_ids
                    for mid in sorted(new_ids, key=lambda value: int(value), reverse=True):
                        fetch_status, msg_data = imap.fetch(mid, "(RFC822)")
                        if fetch_status != "OK":
                            continue
                        message = email_lib.message_from_bytes(msg_data[0][1])
                        body = ""
                        if message.is_multipart():
                            for part in message.walk():
                                if part.get_content_type() in ("text/plain", "text/html"):
                                    try:
                                        body += (part.get_payload(decode=True) or b"").decode(part.get_content_charset() or "utf-8", errors="ignore")
                                    except Exception:
                                        pass
                        else:
                            try:
                                body = (message.get_payload(decode=True) or b"").decode(message.get_content_charset() or "utf-8", errors="ignore")
                            except Exception:
                                pass
                        code = extract_otp_code(body)
                        if code:
                            print(f" 抓到啦! 验证码: {code}")
                            return code
            finally:
                try:
                    imap.logout()
                except Exception:
                    pass
        except Exception as exc:
            last_access_error = _normalize_mail_error(exc)
            err_str = str(exc)
            print(f"\n[IMAP] 轮询出错: {exc}", end="", flush=True)
            if "not connected" in err_str.lower() or "authenticated but not connected" in err_str.lower():
                try:
                    access_token, imap_server = _outlook_get_imap_token(client_id, refresh_token, proxies, email_addr=email_addr)
                    time.sleep(1)
                    continue
                except Exception:
                    pass
        time.sleep(3)
    if not had_successful_mail_fetch and last_access_error:
        if _is_retryable_mail_access_error(last_access_error):
            _set_mail_error(state_email, f"mail_access_retryable:{_normalize_mail_error(last_access_error)}")
        else:
            _set_mail_error(state_email, f"mail_access_error:{_normalize_mail_error(last_access_error)}")
    else:
        _set_mail_error(state_email, "otp_timeout")
    print(" 超时，未收到验证码")
    return ""


def _outlook_fetch_otp(
    email_addr: str,
    client_id: str,
    refresh_token: str,
    known_ids: set | None = None,
    proxies: Any = None,
    timeout: int = 120,
    mail_mode: str = "graph",
    error_email: str | None = None,
) -> str:
    if known_ids is None:
        known_ids = set()
    resolved_mode = _resolve_outlook_mail_mode(mail_mode)
    if resolved_mode == "imap":
        return _outlook_fetch_otp_imap(
            email_addr,
            client_id,
            refresh_token,
            known_ids,
            proxies,
            timeout,
            error_email=error_email,
        )
    return _outlook_fetch_otp_graph(
        email_addr,
        client_id,
        refresh_token,
        known_ids,
        proxies,
        timeout,
        error_email=error_email,
    )


def get_email_and_token(proxies: Any = None) -> tuple:
    if not ctx.HOTMAIL007_API_KEY:
        print("[Error] ctx.HOTMAIL007_API_KEY 未配置")
        return "", ""
    mail_info, remaining = _pop_hotmail007_queue_account(proxies=proxies)
    if not mail_info:
        return "", ""

    email = str(mail_info.get("email") or "").strip()
    primary_email = str(mail_info.get("primary_email") or email).strip() or email
    ctx._hotmail007_credentials[email] = {
        "client_id": mail_info["client_id"],
        "refresh_token": mail_info["refresh_token"],
        "ms_password": mail_info["password"],
        "primary_email": primary_email,
        "mail_mode": mail_info.get("mail_mode", _resolve_outlook_mail_mode(ctx.HOTMAIL007_MAIL_MODE)),
        "source": "hotmail007",
    }
    if email != primary_email:
        print(f"[*] Hotmail007 从别名队列取出邮箱: {email} (原始邮箱: {primary_email}, 剩余: {remaining})")
    else:
        print(f"[*] Hotmail007 从队列取出邮箱: {email} (剩余: {remaining})")
    print("[*] Hotmail007 预获取已有邮件ID...")
    known_ids = _outlook_get_known_ids(primary_email, mail_info["client_id"], mail_info["refresh_token"], proxies)
    ctx._hotmail007_credentials[email]["known_ids"] = known_ids
    return email, email


def get_local_email_and_token(proxies: Any = None) -> tuple:
    if ctx._email_queue is None:
        print("[Error] 本地 Outlook 账号队列未初始化")
        return "", ""
    mode = _resolve_outlook_mail_mode(ctx.LOCAL_OUTLOOK_MAIL_MODE)
    while True:
        account = ctx._email_queue.pop()
        if not account:
            print("[Error] 本地 Outlook 账号已用完")
            return "", ""
        email = account["email"]
        print(f"[*] 从本地账号文件读取 Outlook 账号: {email} (剩余: {len(ctx._email_queue)})")
        try:
            if mode == "imap":
                _outlook_get_imap_token(account["client_id"], account["refresh_token"], proxies, email_addr=email)
            else:
                _outlook_get_graph_token(account["client_id"], account["refresh_token"], proxies)
        except Exception as exc:
            reason = f"{mode}_precheck_failed:{exc}"
            if _should_record_local_outlook_bad_account(reason):
                _record_local_outlook_bad_account(account, reason)
                continue
            if hasattr(ctx._email_queue, "push_front"):
                ctx._email_queue.push_front(account)
            print(f"[Warning] 本地 Outlook 预检遇到瞬时错误，账号已放回队列: {email} ({str(exc)[:120]})")
            return "", ""

        ctx._hotmail007_credentials[email] = {
            "client_id": account["client_id"],
            "refresh_token": account["refresh_token"],
            "ms_password": account.get("password", ""),
            "primary_email": email,
            "mail_mode": mode,
            "source": "local_outlook",
            "account_line": _local_outlook_account_to_line(account),
        }
        print(f"[*] 本地 Outlook 模式预检通过 ({mode.upper()})")
        print("[*] 本地 Outlook 模式预获取已有邮件ID...")
        known_ids = _outlook_get_known_ids(email, account["client_id"], account["refresh_token"], proxies)
        ctx._hotmail007_credentials[email]["known_ids"] = known_ids
        return email, email


def get_oai_code(email: str, proxies: Any = None) -> str:
    creds = ctx._hotmail007_credentials.get(email, {})
    if not creds:
        print(f"[Error] 未找到 {email} 的 Hotmail007 凭据")
        return ""
    mailbox_email = str(creds.get("primary_email") or email).strip() or email
    code = _outlook_fetch_otp(
        mailbox_email,
        creds["client_id"],
        creds["refresh_token"],
        known_ids=creds.get("known_ids", set()),
        proxies=proxies,
        timeout=120,
        mail_mode=creds.get("mail_mode", ctx.HOTMAIL007_MAIL_MODE),
        error_email=email,
    )
    if not code and creds.get("source") == "local_outlook":
        last_error = str(creds.get("last_mail_error") or "").strip()
        if _should_record_local_outlook_bad_account(last_error):
            account_line = str(creds.get("account_line") or "").strip()
            if account_line:
                parts = account_line.split("----", 3)
                if len(parts) == 4:
                    _record_local_outlook_bad_account(
                        {
                            "email": parts[0],
                            "password": parts[1],
                            "client_id": parts[2],
                            "refresh_token": parts[3],
                        },
                        last_error,
                    )
    return code


def delete_temp_email(email: str, proxies: Any = None) -> None:
    del proxies
    ctx._hotmail007_credentials.pop(email, None)
    print(f"[*] Hotmail007 邮箱 {email} 本地凭据已清理")
