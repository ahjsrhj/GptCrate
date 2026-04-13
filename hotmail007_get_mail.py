#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
from typing import Any

from curl_cffi import requests

from gpt_register import context as ctx


def _is_user_cancelled_request_error(error: Any) -> bool:
    text = str(error or "").strip().lower()
    if not text:
        return False
    return "curl: (23)" in text and "failure writing output to destination" in text


def _extract_error_message(result: dict[str, Any] | None) -> str:
    body = (result or {}).get("body")
    if isinstance(body, dict):
        return str(body.get("message") or body.get("msg") or "").strip()
    return str(body or "").strip()


def _is_timeout_error(result: dict[str, Any] | None) -> bool:
    text = _extract_error_message(result).lower()
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


def _summarize_body(body: Any, limit: int = 240) -> str:
    try:
        text = json.dumps(body, ensure_ascii=False)
    except Exception:
        text = str(body)
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3]}..."


def _print_retry_message(
    result: dict[str, Any],
    *,
    attempt: int,
) -> None:
    error_message = _extract_error_message(result) or "未知错误"
    body_summary = _summarize_body(result.get("body"))
    print(
        f"[重试] 第 {attempt} 次请求失败 | HTTP={result.get('status_code')} | "
        f"错误={error_message} | 立即继续"
    )
    print(f"[重试] 响应摘要: {body_summary}", flush=True)


def _format_mail_lines(body: Any) -> list[str]:
    if not isinstance(body, dict):
        return []

    rows = body.get("data")
    if not isinstance(rows, list):
        return []

    formatted: list[str] = []
    for row in rows:
        if not isinstance(row, str):
            continue
        parts = row.split(":")
        if len(parts) < 4:
            continue
        email = parts[0].strip()
        password = parts[1].strip()
        client_id = parts[-1].strip()
        refresh_token = ":".join(parts[2:-1]).strip()
        formatted.append(f"{email}----{password}----{client_id}----{refresh_token}")
    return formatted


def _refresh_resin_proxy_on_timeout(
    *,
    current_proxy: str | None,
    resin_state: ctx.ResinRunState | None,
    result: dict[str, Any],
) -> bool:
    if current_proxy:
        return False
    if resin_state is None:
        return False
    if not ctx.is_resin_enabled():
        return False
    if not _is_timeout_error(result):
        return False

    new_account = ctx.get_resin_startup_account(force_new=True, resin_state=resin_state)
    print(f"[*] 请求超时，已切换 Resin 启动账号: {new_account}")
    print(f"[*] 已切换新代理: {ctx.build_proxy_url(current_proxy, resin_state=resin_state) or '直连'}")
    return True


def build_get_mail_url(
    api_url: str,
    *,
    client_key: str,
    mail_type: str,
    quantity: int,
) -> str:
    base = f"{api_url.rstrip('/')}/api/mail/getMail"
    params = {
        "clientKey": client_key,
        "mailType": mail_type,
        "quantity": quantity,
    }
    query = "&".join(
        f"{key}={urllib.parse.quote(str(value))}"
        for key, value in params.items()
        if value not in (None, "")
    )
    return f"{base}?{query}" if query else base


def request_get_mail(
    api_url: str,
    *,
    client_key: str,
    mail_type: str,
    quantity: int,
    proxies: Any = None,
    timeout: float = 15,
) -> dict[str, Any]:
    url = build_get_mail_url(
        api_url,
        client_key=client_key,
        mail_type=mail_type,
        quantity=quantity,
    )
    try:
        response = requests.get(
            url,
            proxies=proxies,
            verify=ctx._ssl_verify(),
            timeout=timeout,
            impersonate="safari",
        )
        try:
            body = response.json()
        except Exception:
            body = {
                "success": False,
                "message": "响应不是合法 JSON",
                "text": getattr(response, "text", ""),
            }
        return {
            "ok": bool(isinstance(body, dict) and body.get("success") and body.get("code") == 0),
            "url": url,
            "status_code": getattr(response, "status_code", None),
            "body": body,
        }
    except KeyboardInterrupt:
        raise
    except Exception as exc:
        if _is_user_cancelled_request_error(exc):
            raise KeyboardInterrupt from exc
        return {
            "ok": False,
            "url": url,
            "status_code": None,
            "body": {
                "success": False,
                "message": str(exc),
            },
        }


def fetch_get_mail_with_retry(
    api_url: str,
    *,
    client_key: str,
    mail_type: str,
    quantity: int,
    current_proxy: str | None = None,
    resin_state: ctx.ResinRunState | None = None,
    timeout: float = 15,
) -> tuple[dict[str, Any], int]:
    attempt = 0

    while True:
        attempt += 1
        result = request_get_mail(
            api_url,
            client_key=client_key,
            mail_type=mail_type,
            quantity=quantity,
            proxies=ctx.build_proxies(current_proxy, resin_state=resin_state),
            timeout=timeout,
        )
        if result["ok"]:
            return result, attempt

        _refresh_resin_proxy_on_timeout(
            current_proxy=current_proxy,
            resin_state=resin_state,
            result=result,
        )
        _print_retry_message(
            result,
            attempt=attempt,
        )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="调用 Hotmail007 的 /api/mail/getMail 接口，并在失败时自动重试。",
    )
    parser.add_argument("--api-url", default=ctx.HOTMAIL007_API_URL, help="接口基础地址，默认读取 .env")
    parser.add_argument("--api-key", default=ctx.HOTMAIL007_API_KEY, help="Hotmail007 API Key，默认读取 .env")
    parser.add_argument(
        "--mail-type",
        default=ctx.HOTMAIL007_MAIL_TYPE,
        help="邮箱类型，默认读取 .env 中的 HOTMAIL007_MAIL_TYPE",
    )
    parser.add_argument("--quantity", type=int, default=1, help="拉取数量，默认 1")
    parser.add_argument("--timeout", type=float, default=15.0, help="单次请求超时时间，默认 15 秒")
    parser.add_argument("--proxy", default=ctx.SINGLE_PROXY or None, help="单代理地址，默认读取 PROXY")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    if not args.api_key:
        print("缺少 API Key，请在 .env 中配置 HOTMAIL007_API_KEY 或通过 --api-key 传入。", file=sys.stderr)
        return 1
    if args.quantity <= 0:
        print("--quantity 必须大于 0。", file=sys.stderr)
        return 1

    use_resin_proxy = ctx.is_resin_enabled() and not args.proxy
    runtime_resin_state = ctx.ResinRunState() if use_resin_proxy else None
    if use_resin_proxy:
        try:
            ctx.parse_resin_url()
        except ValueError as exc:
            print(f"Resin 配置错误: {exc}", file=sys.stderr)
            return 1

    try:
        result, attempts = fetch_get_mail_with_retry(
            args.api_url,
            client_key=args.api_key,
            mail_type=args.mail_type,
            quantity=args.quantity,
            current_proxy=args.proxy or None,
            resin_state=runtime_resin_state,
            timeout=args.timeout,
        )
    except KeyboardInterrupt:
        print("\n已停止。", file=sys.stderr)
        return 130

    print(f"请求 URL: {result.get('url')}")
    print(f"尝试次数: {attempts}")
    print("重试策略: 无限重试")
    print(f"HTTP 状态码: {result.get('status_code')}")
    body = result.get("body")
    if result.get("ok"):
        formatted_lines = _format_mail_lines(body)
        print("格式化结果:")
        if formatted_lines:
            for line in formatted_lines:
                print(line)
        else:
            print("未解析到可格式化的数据")
    else:
        print("接口响应:")
        print(json.dumps(body, ensure_ascii=False, indent=2))

    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
