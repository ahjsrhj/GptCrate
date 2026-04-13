from __future__ import annotations

import json
import random
import re
import string
import time
import urllib.parse
from datetime import datetime
from typing import Any, Callable, Optional

from curl_cffi import requests

from . import context as ctx
from . import mail, oauth
from .ui import rich_print as print


_FIRST_NAMES = [
    "James", "John", "Robert", "Michael", "David", "William", "Richard",
    "Joseph", "Thomas", "Christopher", "Daniel", "Matthew", "Anthony",
    "Mary", "Patricia", "Jennifer", "Linda", "Elizabeth", "Barbara",
    "Sarah", "Jessica", "Karen", "Emily", "Olivia", "Emma", "Sophia",
]

_LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Rodriguez", "Martinez", "Wilson", "Anderson", "Taylor",
    "Thomas", "Moore", "Jackson", "Martin", "Lee", "Harris", "Clark",
]
_TRANSIENT_RETRY_LIMIT = 3
_INITIAL_DEVICE_ID_RETRY_LIMIT = 1
_INITIAL_PROXY_REFRESH_LIMIT = 3
_RESIN_REQUEST_PROXY_REFRESH_LIMIT = 5
_OTP_RESEND_LIMIT = 4
_OTP_MAIL_FETCH_RETRY_LIMIT = 3


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


def _call_with_timeout_retry(action, *, label: str):
    last_error: Exception | None = None
    for retry_count in range(_TRANSIENT_RETRY_LIMIT + 1):
        try:
            return action()
        except Exception as exc:
            last_error = exc
            if not _is_timeout_error(exc) or retry_count >= _TRANSIENT_RETRY_LIMIT:
                raise
            print(f"[*] {label} 超时，继续重试 ({retry_count + 1}/{_TRANSIENT_RETRY_LIMIT})...")
            time.sleep(2)
    if last_error:
        raise last_error
    raise RuntimeError(f"{label} 失败")


def _new_session(proxies: Any = None) -> requests.Session:
    return requests.Session(proxies=proxies, impersonate="safari")


def _check_network_ready(session: requests.Session, proxies: Any = None) -> bool:
    if ctx._skip_net_check():
        return True
    try:
        trace = _call_with_timeout_retry(
            lambda: session.get(
                "https://cloudflare.com/cdn-cgi/trace",
                proxies=proxies,
                verify=ctx._ssl_verify(),
                timeout=10,
            ),
            label="网络连接检查",
        ).text
        loc_re = re.search(r"^loc=(.+)$", trace, re.MULTILINE)
        loc = loc_re.group(1) if loc_re else None
        print(f"[*] 当前 IP 所在地: {loc}")
        if loc == "CN" or loc == "HK":
            raise RuntimeError("检查代理哦w - 所在地不支持")
        return True
    except Exception as exc:
        print(f"[Error] 网络连接检查失败: {exc}")
        return False


def _bootstrap_authorize_continue_detailed(
    session: requests.Session,
    auth_url: str,
    proxies: Any = None,
    *,
    device_label: str = "Device ID",
    device_id_retry_limit: int = _TRANSIENT_RETRY_LIMIT,
    log_missing_device_error: bool = True,
) -> tuple[str, str, str]:
    device_retry_count = 0
    sentinel_retry_count = 0

    while True:
        _call_with_timeout_retry(
            lambda: session.get(
                auth_url,
                proxies=proxies,
                verify=True,
                timeout=15,
            ),
            label="拉起授权页",
        )
        did = session.cookies.get("oai-did")
        print(f"[*] {device_label}: {did}")
        if not did:
            if device_retry_count >= device_id_retry_limit:
                if log_missing_device_error:
                    print("[Error] 未获取到 Device ID")
                return "", "", "missing_device_id"
            device_retry_count += 1
            retry_total = max(device_id_retry_limit, 1)
            print(f"[*] Device ID 为空，重新初始化授权页 ({device_retry_count}/{retry_total})...")
            time.sleep(2)
            continue

        sen_req_body = f'{{"p":"","id":"{did}","flow":"authorize_continue"}}'
        sen_resp = _call_with_timeout_retry(
            lambda: requests.post(
                "https://sentinel.openai.com/backend-api/sentinel/req",
                headers={
                    "origin": "https://sentinel.openai.com",
                    "referer": "https://sentinel.openai.com/backend-api/sentinel/frame.html?sv=20260219f9f6",
                    "content-type": "text/plain;charset=UTF-8",
                },
                data=sen_req_body,
                proxies=proxies,
                impersonate="safari",
                verify=ctx._ssl_verify(),
                timeout=15,
            ),
            label="Sentinel 请求",
        )
        if sen_resp.status_code == 200:
            token = sen_resp.json().get("token", "")
            if token:
                sentinel = f'{{"p": "", "t": "", "c": "{token}", "id": "{did}", "flow": "authorize_continue"}}'
                return did, sentinel, ""
            print("[Error] Sentinel 响应缺少 token")
            return "", "", "missing_sentinel_token"
        if sen_resp.status_code == 403:
            if sentinel_retry_count >= _TRANSIENT_RETRY_LIMIT:
                print(f"[Error] Sentinel 异常拦截，状态码: {sen_resp.status_code}")
                return "", "", "sentinel_403"
            sentinel_retry_count += 1
            print(f"[*] Sentinel 403，继续重试 ({sentinel_retry_count}/{_TRANSIENT_RETRY_LIMIT})...")
            time.sleep(2)
            continue
        print(f"[Error] Sentinel 异常拦截，状态码: {sen_resp.status_code}")
        return "", "", f"sentinel_{sen_resp.status_code}"


def _bootstrap_authorize_continue(
    session: requests.Session,
    auth_url: str,
    proxies: Any = None,
    *,
    device_label: str = "Device ID",
) -> tuple[str, str]:
    did, sentinel, _ = _bootstrap_authorize_continue_detailed(
        session,
        auth_url,
        proxies=proxies,
        device_label=device_label,
    )
    return did, sentinel


def _bootstrap_device_with_proxy_refresh(
    auth_url: str,
    proxy: Optional[str],
    get_next_proxy: Optional[Callable[[], Optional[str]]] = None,
    resin_state: Optional[ctx.ResinRunState] = None,
    *,
    session: Optional[requests.Session] = None,
    network_checked: bool = False,
    device_label: str = "Device ID",
    retry_reason: str = "获取 Device ID 失败",
) -> tuple[requests.Session, Optional[str], Any, str, str]:
    current_proxy = proxy
    proxies = ctx.build_proxies(current_proxy, resin_state=resin_state)
    session = session or _new_session(proxies=proxies)
    proxy_refresh_count = 0

    while True:
        if not network_checked and not _check_network_ready(session, proxies=proxies):
            return session, current_proxy, proxies, "", ""
        network_checked = False

        did, sentinel, reason = _bootstrap_authorize_continue_detailed(
            session,
            auth_url,
            proxies=proxies,
            device_label=device_label,
            device_id_retry_limit=_INITIAL_DEVICE_ID_RETRY_LIMIT,
            log_missing_device_error=False,
        )
        if did and sentinel:
            return session, current_proxy, proxies, did, sentinel

        if reason != "missing_device_id":
            return session, current_proxy, proxies, "", ""

        if proxy_refresh_count >= _INITIAL_PROXY_REFRESH_LIMIT:
            print("[Error] 未获取到 Device ID")
            return session, current_proxy, proxies, "", ""

        if resin_state is not None and ctx.is_resin_enabled() and not current_proxy:
            proxy_refresh_count += 1
            print(f"[*] {retry_reason}，重新生成 Resin 启动账号 ({proxy_refresh_count}/{_INITIAL_PROXY_REFRESH_LIMIT})...")
            new_account = ctx.get_resin_startup_account(force_new=True, resin_state=resin_state)
            proxies = ctx.build_proxies(current_proxy, resin_state=resin_state)
            session = _new_session(proxies=proxies)
            print(f"[*] 已切换 Resin 启动账号: {new_account}")
            print(f"[*] 已切换新代理: {ctx.build_proxy_url(current_proxy, resin_state=resin_state) or '直连'}")
            continue

        if not get_next_proxy:
            print("[Error] 未获取到 Device ID")
            return session, current_proxy, proxies, "", ""

        next_proxy = get_next_proxy()
        if next_proxy == current_proxy:
            print("[*] 代理池没有可切换的新代理，停止重新获取代理")
            print("[Error] 未获取到 Device ID")
            return session, current_proxy, proxies, "", ""

        proxy_refresh_count += 1
        print(f"[*] {retry_reason}，重新获取代理 ({proxy_refresh_count}/{_INITIAL_PROXY_REFRESH_LIMIT})...")
        current_proxy = next_proxy
        proxies = ctx.build_proxies(current_proxy, resin_state=resin_state)
        session = _new_session(proxies=proxies)
        print(f"[*] 已切换新代理: {ctx.build_proxy_url(current_proxy, resin_state=resin_state) or '直连'}")


def _bootstrap_initial_device_with_proxy_refresh(
    auth_url: str,
    proxy: Optional[str],
    get_next_proxy: Optional[Callable[[], Optional[str]]] = None,
    resin_state: Optional[ctx.ResinRunState] = None,
    *,
    network_checked: bool = False,
) -> tuple[requests.Session, Optional[str], Any, str, str]:
    return _bootstrap_device_with_proxy_refresh(
        auth_url,
        proxy,
        get_next_proxy=get_next_proxy,
        resin_state=resin_state,
        network_checked=network_checked,
    )


def _bootstrap_relogin_device_with_proxy_refresh(
    session: requests.Session,
    auth_url: str,
    proxy: Optional[str],
    get_next_proxy: Optional[Callable[[], Optional[str]]] = None,
    resin_state: Optional[ctx.ResinRunState] = None,
    *,
    network_checked: bool = False,
) -> tuple[requests.Session, Optional[str], Any, str, str]:
    return _bootstrap_device_with_proxy_refresh(
        auth_url,
        proxy,
        get_next_proxy=get_next_proxy,
        resin_state=resin_state,
        session=session,
        network_checked=network_checked,
        device_label="重登录 Device ID",
        retry_reason="重登录获取 Device ID 失败",
    )


def _is_phone_challenge_response(payload: dict) -> bool:
    continue_url = str(payload.get("continue_url") or "").lower()
    page_type = str((payload.get("page") or {}).get("type") or "").lower()
    return "add-phone" in continue_url or page_type == "add_phone"

def _random_user_info() -> dict:
    name = f"{random.choice(_FIRST_NAMES)} {random.choice(_LAST_NAMES)}"
    year = random.randint(datetime.now().year - 45, datetime.now().year - 18)
    month = random.randint(1, 12)
    day = random.randint(1, 28)
    return {"name": name, "birthdate": f"{year}-{month:02d}-{day:02d}"}

def _generate_password(length: int = 16) -> str:
    """生成符合 OpenAI 要求的随机强密码（大小写+数字+特殊字符）"""
    upper = random.choices(string.ascii_uppercase, k=2)
    lower = random.choices(string.ascii_lowercase, k=2)
    digits = random.choices(string.digits, k=2)
    specials = random.choices("!@#$%&*", k=2)
    rest_len = length - 8
    pool = string.ascii_letters + string.digits + "!@#$%&*"
    rest = random.choices(pool, k=rest_len)
    chars = upper + lower + digits + specials + rest
    random.shuffle(chars)
    return "".join(chars)


def _resend_email_otp(
    session: requests.Session,
    sentinel: str,
    proxies: Any = None,
) -> None:
    try:
        oauth._post_with_retry(
            session,
            "https://auth.openai.com/api/accounts/email-otp/resend",
            headers={
                "openai-sentinel-token": sentinel,
                "content-type": "application/json",
            },
            json_body={},
            proxies=proxies,
            timeout=15,
            retries=1,
        )
        time.sleep(2)
    except Exception as exc:
        print(f"[*] 重发 OTP 异常: {exc}")


def _collect_email_otp(
    session: requests.Session,
    *,
    sentinel: str,
    dev_token: str,
    email: str,
    proxies: Any = None,
    processed_mails: set | None = None,
) -> str:
    if processed_mails is None:
        processed_mails = set()

    for resend_attempt in range(_OTP_RESEND_LIMIT + 1):
        mail_fetch_retry_count = 0
        while True:
            code = mail.get_oai_code(token=dev_token, email=email, proxies=proxies, seen_ids=processed_mails)
            if code:
                return code

            last_mail_error = str(mail.get_last_mail_error(email) or "").strip()
            if mail.should_retry_mail_fetch_without_resend(email) and mail_fetch_retry_count < _OTP_MAIL_FETCH_RETRY_LIMIT:
                mail_fetch_retry_count += 1
                suffix = f": {last_mail_error[:120]}" if last_mail_error else ""
                print(
                    f"\n[*] 邮箱访问异常，先重新访问邮箱 ({mail_fetch_retry_count}/{_OTP_MAIL_FETCH_RETRY_LIMIT}){suffix}"
                )
                time.sleep(2)
                continue
            break

        if resend_attempt >= _OTP_RESEND_LIMIT:
            break

        print(f"\n[*] OTP 重试 {resend_attempt + 1}/{_OTP_RESEND_LIMIT}，重新发送验证码...")
        _resend_email_otp(session, sentinel, proxies=proxies)

    return ""


def _refresh_resin_startup_proxy_for_retry(
    current_proxy: Optional[str],
    resin_state: Optional[ctx.ResinRunState],
    *,
    retry_count: int,
    reason: str,
) -> bool:
    if current_proxy or resin_state is None or not ctx.is_resin_enabled():
        return False
    if retry_count >= _RESIN_REQUEST_PROXY_REFRESH_LIMIT:
        return False

    print(
        f"[*] {reason}，回退到新的 Resin 启动账号继续重试 "
        f"({retry_count + 1}/{_RESIN_REQUEST_PROXY_REFRESH_LIMIT})..."
    )
    new_account = ctx.get_resin_startup_account(force_new=True, resin_state=resin_state)
    print(f"[*] 已切换 Resin 启动账号: {new_account}")
    print(f"[*] 已切换新代理: {ctx.build_proxy_url(current_proxy, resin_state=resin_state) or '直连'}")
    return True

def run(proxy: Optional[str], get_next_proxy: Optional[Callable[[], Optional[str]]] = None) -> tuple:
    """运行注册流程，返回 (token_json, password, email, fail_reason, used_proxy)
    失败时返回 (None/特殊标记, None, email, fail_reason, used_proxy)
    fail_reason: 403_forbidden, signup_form_error, password_error, otp_timeout,
                 account_create_error, callback_error, network_error, other_error
    """
    current_proxy = proxy
    resin_state = ctx.ResinRunState() if ctx.is_resin_enabled() and not current_proxy else None

    provider_proxies: Any = ctx.build_proxies(current_proxy, resin_state=resin_state)
    email, dev_token = mail.get_email_and_token(provider_proxies)
    if not email or not dev_token:
        return None, None, email, "other_error", ctx.build_proxy_url(current_proxy, resin_state=resin_state)
    print(f"[*] 成功获取临时邮箱与授权: {email}")
    masked = dev_token[:8] + "..." if dev_token else ""
    print(f"[*] 临时邮箱 JWT: {masked}")

    if resin_state is not None:
        resin_state.set_current_account(email)

    request_retry_count = 0

    while True:
        proxies: Any = ctx.build_proxies(current_proxy, resin_state=resin_state)
        if resin_state is not None:
            print(f"[*] 当前使用的粘性代理: {(proxies or {}).get('http') or '直连'}")
        s = _new_session(proxies=proxies)

        if not _check_network_ready(s, proxies=proxies):
            if _refresh_resin_startup_proxy_for_retry(
                current_proxy,
                resin_state,
                retry_count=request_retry_count,
                reason="网络连接检查失败",
            ):
                request_retry_count += 1
                continue
            return None, None, email, "network_error", ctx.build_proxy_url(current_proxy, resin_state=resin_state)

        oauth_start = oauth.generate_oauth_url()
        url = oauth_start.auth_url

        try:
            s, current_proxy, proxies, did, sentinel = _bootstrap_initial_device_with_proxy_refresh(
                url,
                current_proxy,
                get_next_proxy=get_next_proxy,
                resin_state=resin_state,
                network_checked=True,
            )
            if not did or not sentinel:
                if _refresh_resin_startup_proxy_for_retry(
                    current_proxy,
                    resin_state,
                    retry_count=request_retry_count,
                    reason="初始化授权失败",
                ):
                    request_retry_count += 1
                    continue
                return None, None, email, "other_error", ctx.build_proxy_url(current_proxy, resin_state=resin_state)

            signup_body = f'{{"username":{{"value":"{email}","kind":"email"}},"screen_hint":"signup"}}'

            signup_resp = _call_with_timeout_retry(
                lambda: s.post(
                    "https://auth.openai.com/api/accounts/authorize/continue",
                    headers={
                        "referer": "https://auth.openai.com/create-account",
                        "accept": "application/json",
                        "content-type": "application/json",
                        "openai-sentinel-token": sentinel,
                    },
                    data=signup_body,
                    proxies=proxies,
                    verify=ctx._ssl_verify(),
                    timeout=30,
                ),
                label="提交注册表单",
            )
            signup_status = signup_resp.status_code
            print(f"[*] 提交注册表单状态: {signup_status}")

            if signup_status == 403:
                print("[Error] 提交注册表单返回 403，中断本次运行，将在10秒后重试...")
                return "retry_403", None, email, "403_forbidden", ctx.build_proxy_url(current_proxy, resin_state=resin_state)
            if signup_status != 200:
                print("[Error] 提交注册表单失败，跳过本次流程")
                print(signup_resp.text)
                return None, None, email, "signup_form_error", ctx.build_proxy_url(current_proxy, resin_state=resin_state)

            password = _generate_password()
            register_body = json.dumps({"password": password, "username": email})
            print(f"[*] 生成随机密码: {password[:4]}****")

            pwd_resp = _call_with_timeout_retry(
                lambda: s.post(
                    "https://auth.openai.com/api/accounts/user/register",
                    headers={
                        "referer": "https://auth.openai.com/create-account/password",
                        "accept": "application/json",
                        "content-type": "application/json",
                        "openai-sentinel-token": sentinel,
                    },
                    data=register_body,
                    proxies=proxies,
                    verify=ctx._ssl_verify(),
                    timeout=30,
                ),
                label="提交注册密码",
            )
            print(f"[*] 提交注册(密码)状态: {pwd_resp.status_code}")
            if pwd_resp.status_code != 200:
                print(pwd_resp.text)
                return None, None, email, "password_error", ctx.build_proxy_url(current_proxy, resin_state=resin_state)

            try:
                register_json = pwd_resp.json()
                register_continue = register_json.get("continue_url", "")
                register_page = (register_json.get("page") or {}).get("type", "")
                print(f"[*] 注册响应 continue_url: {register_continue}")
                print(f"[*] 注册响应 page.type: {register_page}")
            except Exception:
                register_continue = ""
                register_page = ""
                print(f"[*] 注册响应(raw): {pwd_resp.text[:300]}")

            need_otp = "email-verification" in register_continue or "verify" in register_continue
            if not need_otp and register_page:
                need_otp = "verification" in register_page or "otp" in register_page

            if need_otp:
                print("[*] 需要邮箱验证，开始等待验证码...")

                if register_continue:
                    otp_send_url = register_continue
                    if not otp_send_url.startswith("http"):
                        otp_send_url = f"https://auth.openai.com{otp_send_url}"
                    print(f"[*] 触发发送 OTP: {otp_send_url}")
                    otp_send_resp = oauth._post_with_retry(
                        s,
                        otp_send_url,
                        headers={
                            "referer": "https://auth.openai.com/create-account/password",
                            "accept": "application/json",
                            "content-type": "application/json",
                            "openai-sentinel-token": sentinel,
                        },
                        json_body={},
                        proxies=proxies,
                        timeout=30,
                        retries=2,
                    )
                    print(f"[*] OTP 发送状态: {otp_send_resp.status_code}")
                    if otp_send_resp.status_code != 200:
                        print(otp_send_resp.text)

                processed_mails = set()
                code = _collect_email_otp(
                    s,
                    sentinel=sentinel,
                    dev_token=dev_token,
                    email=email,
                    proxies=proxies,
                    processed_mails=processed_mails,
                )
                if not code:
                    print("[Error] 多次重试后仍未收到验证码，跳过")
                    return None, None, email, "otp_timeout", ctx.build_proxy_url(current_proxy, resin_state=resin_state)

                print("[*] 开始校验验证码...")
                code_resp = oauth._post_with_retry(
                    s,
                    "https://auth.openai.com/api/accounts/email-otp/validate",
                    headers={
                        "referer": "https://auth.openai.com/email-verification",
                        "accept": "application/json",
                        "content-type": "application/json",
                        "openai-sentinel-token": sentinel,
                    },
                    json_body={"code": code},
                    proxies=proxies,
                    timeout=30,
                    retries=2,
                )
                print(f"[*] 验证码校验状态: {code_resp.status_code}")
                if code_resp.status_code != 200:
                    print(code_resp.text)
            else:
                print("[*] 密码注册无需邮箱验证，跳过 OTP 步骤")

            user_info = _random_user_info()
            print(f"[*] 开始创建账户 (昵称: {user_info['name']})...")
            create_account_resp = oauth._post_with_retry(
                s,
                "https://auth.openai.com/api/accounts/create_account",
                headers={
                    "referer": "https://auth.openai.com/about-you",
                    "accept": "application/json",
                    "content-type": "application/json",
                },
                json_body=user_info,
                proxies=proxies,
                timeout=30,
                retries=2,
            )
            create_account_status = create_account_resp.status_code
            print(f"[*] 账户创建状态: {create_account_status}")

            if create_account_status != 200:
                print(create_account_resp.text)
                return None, None, email, "account_create_error", ctx.build_proxy_url(current_proxy, resin_state=resin_state)
            try:
                create_account_json = create_account_resp.json()
            except Exception:
                create_account_json = {}

            if _is_phone_challenge_response(create_account_json):
                print("[*] 账户创建后进入手机号验证步骤，尝试跳过...")
                print(create_account_resp.text)
                # 尝试跳过手机号验证，继续后续流程
                # 有时服务端虽然返回 add_phone，但静默重登录后仍能获取 token
                print("[*] 尝试继续静默重登录流程...")
            else:
                print("[*] 账户创建完毕，执行静默重登录...")
            s.cookies.clear()

            oauth_start = oauth.generate_oauth_url()
            s, current_proxy, proxies, new_did, sentinel2 = _bootstrap_relogin_device_with_proxy_refresh(
                s,
                oauth_start.auth_url,
                current_proxy,
                get_next_proxy=get_next_proxy,
                resin_state=resin_state,
                network_checked=True,
            )
            new_did = new_did or did
            if not new_did or not sentinel2:
                return None, None, email, "other_error", ctx.build_proxy_url(current_proxy, resin_state=resin_state)

            oauth._post_with_retry(
                s,
                "https://auth.openai.com/api/accounts/authorize/continue",
                headers={
                    "openai-sentinel-token": sentinel2,
                    "content-type": "application/json",
                },
                json_body={"username": {"value": email, "kind": "email"}, "screen_hint": "login"},
                proxies=proxies,
            )

            pwd_login_resp = oauth._post_with_retry(
                s,
                "https://auth.openai.com/api/accounts/password/verify",
                headers={
                    "openai-sentinel-token": sentinel2,
                    "content-type": "application/json",
                },
                json_body={"password": password},
                proxies=proxies,
            )
            print(f"[*] 密码登录状态: {pwd_login_resp.status_code}")

            if pwd_login_resp.status_code == 200:
                try:
                    pwd_json = pwd_login_resp.json()
                    pwd_page = (pwd_json.get("page") or {}).get("type", "")
                    if "otp" in pwd_page or "verify" in str(pwd_json.get("continue_url", "")):
                        print("[*] 登录触发二次邮箱验证，尝试使用第一次的验证码...")
                        # 二次验证码通常和第一次相同，直接复用
                        code2 = code
                        if not code2:
                            print("[Error] 第一次验证码为空，无法复用")
                            return None, None, email, "otp_timeout", current_proxy
                        print(f"[*] 使用第一次的验证码: {code2}")
                        code2_resp = oauth._post_with_retry(
                            s,
                            "https://auth.openai.com/api/accounts/email-otp/validate",
                            headers={
                                "openai-sentinel-token": sentinel2,
                                "content-type": "application/json",
                            },
                            json_body={"code": code2},
                            proxies=proxies,
                        )
                        print(f"[*] 二次验证码校验状态: {code2_resp.status_code}")
                        if code2_resp.status_code != 200:
                            print(code2_resp.text)
                            return None, None, email, "otp_timeout", ctx.build_proxy_url(current_proxy, resin_state=resin_state)
                except Exception:
                    pass

            auth_cookie = s.cookies.get("oai-client-auth-session")
            if not auth_cookie:
                print("[Error] 重登录后未能获取授权 Cookie")
                return None, None, email, "callback_error", ctx.build_proxy_url(current_proxy, resin_state=resin_state)

            auth_json = {}
            raw_val = auth_cookie.strip()
            try:
                decoded_val = urllib.parse.unquote(raw_val)
                if decoded_val != raw_val:
                    raw_val = decoded_val
            except Exception:
                pass
            for part in raw_val.split("."):
                decoded = oauth._decode_jwt_segment(part)
                if isinstance(decoded, dict) and "workspaces" in decoded:
                    auth_json = decoded
                    break

            workspaces = auth_json.get("workspaces") or []
            if not workspaces:
                print("[Error] 重登录后 Cookie 里仍没有 workspace 信息")
                return None, None, email, "callback_error", ctx.build_proxy_url(current_proxy, resin_state=resin_state)
            workspace_id = str((workspaces[0] or {}).get("id") or "").strip()
            if not workspace_id:
                print("[Error] 无法解析 workspace_id")
                return None, None, email, "callback_error", ctx.build_proxy_url(current_proxy, resin_state=resin_state)

            select_body = f'{{"workspace_id":"{workspace_id}"}}'
            print("[*] 开始选择 workspace...")
            select_resp = oauth._post_with_retry(
                s,
                "https://auth.openai.com/api/accounts/workspace/select",
                headers={
                    "referer": "https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
                    "content-type": "application/json",
                },
                data=select_body,
                proxies=proxies,
                timeout=30,
                retries=2,
            )

            if select_resp.status_code != 200:
                print(f"[Error] 选择 workspace 失败，状态码: {select_resp.status_code}")
                print(select_resp.text)
                return None, None, email, "callback_error", ctx.build_proxy_url(current_proxy, resin_state=resin_state)

            continue_url = str((select_resp.json() or {}).get("continue_url") or "").strip()
            if not continue_url:
                print("[Error] workspace/select 响应里缺少 continue_url")
                return None, None, email, "callback_error", ctx.build_proxy_url(current_proxy, resin_state=resin_state)

            try:
                select_data = select_resp.json()
                orgs = (select_data.get("data") or {}).get("orgs") or []
                if orgs:
                    org_id = str((orgs[0] or {}).get("id") or "").strip()
                    if org_id:
                        org_body = {"org_id": org_id}
                        projects = (orgs[0] or {}).get("projects") or []
                        if projects:
                            org_body["project_id"] = str((projects[0] or {}).get("id") or "").strip()
                        print(f"[*] 选择组织: {org_id}")
                        org_resp = oauth._post_with_retry(
                            s,
                            "https://auth.openai.com/api/accounts/organization/select",
                            headers={
                                "content-type": "application/json",
                                "openai-sentinel-token": sentinel2,
                            },
                            json_body=org_body,
                            proxies=proxies,
                        )
                        if org_resp.status_code in [301, 302, 303, 307, 308]:
                            continue_url = org_resp.headers.get("Location", continue_url)
                        elif org_resp.status_code == 200:
                            try:
                                continue_url = org_resp.json().get("continue_url", continue_url)
                            except Exception:
                                pass
            except Exception as e:
                print(f"[*] 组织选择异常(非致命): {e}")

            current_url = continue_url
            for _ in range(15):
                final_resp = _call_with_timeout_retry(
                    lambda: s.get(
                        current_url,
                        allow_redirects=False,
                        proxies=proxies,
                        verify=ctx._ssl_verify(),
                        timeout=15,
                    ),
                    label="跟踪重定向链",
                )

                if final_resp.status_code in [301, 302, 303, 307, 308]:
                    next_url = urllib.parse.urljoin(
                        current_url, final_resp.headers.get("Location") or ""
                    )
                elif final_resp.status_code == 200:
                    if "consent_challenge=" in current_url:
                        c_resp = _call_with_timeout_retry(
                            lambda: s.post(
                                current_url,
                                data={"action": "accept"},
                                allow_redirects=False,
                                proxies=proxies,
                                verify=ctx._ssl_verify(),
                                timeout=15,
                            ),
                            label="提交授权确认",
                        )
                        next_url = (
                            urllib.parse.urljoin(
                                current_url, c_resp.headers.get("Location") or ""
                            )
                            if c_resp.status_code in [301, 302, 303, 307, 308]
                            else ""
                        )
                    else:
                        meta_match = re.search(
                            r'content=["\']?\d+;\s*url=([^"\'>\s]+)',
                            final_resp.text,
                            re.IGNORECASE,
                        )
                        next_url = (
                            urllib.parse.urljoin(current_url, meta_match.group(1))
                            if meta_match
                            else ""
                        )
                    if not next_url:
                        break
                else:
                    break

                if "code=" in next_url and "state=" in next_url:
                    token_json = oauth.submit_callback_url(
                        callback_url=next_url,
                        code_verifier=oauth_start.code_verifier,
                        redirect_uri=oauth_start.redirect_uri,
                        expected_state=oauth_start.state,
                    )
                    return token_json, password, email, "", ctx.build_proxy_url(current_proxy, resin_state=resin_state)
                current_url = next_url

            print("[Error] 未能在重定向链中捕获到最终 Callback URL")
            return None, None, email, "callback_error", ctx.build_proxy_url(current_proxy, resin_state=resin_state)

        except Exception as e:
            print(f"[Error] 运行时发生错误: {e}")
            if _refresh_resin_startup_proxy_for_retry(
                current_proxy,
                resin_state,
                retry_count=request_retry_count,
                reason="请求失败",
            ):
                request_retry_count += 1
                continue
            return None, None, email, "other_error", ctx.build_proxy_url(current_proxy, resin_state=resin_state)
