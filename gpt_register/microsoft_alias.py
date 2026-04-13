from __future__ import annotations

import random
import string


def normalize_microsoft_alias_base_email(email: str) -> str:
    raw_email = str(email or "").strip()
    if "@" not in raw_email:
        raise ValueError("微软邮箱别名生成失败：邮箱格式不正确")
    local, domain = raw_email.split("@", 1)
    base_local = local.split("+", 1)[0]
    return f"{base_local}@{domain}"


def generate_microsoft_alias_email(email: str) -> str:
    base_email = normalize_microsoft_alias_base_email(email)
    local, domain = base_email.split("@", 1)
    suffix = "".join(random.choices(string.ascii_lowercase, k=6))
    return f"{local}+{suffix}@{domain}"


def expand_microsoft_alias_emails(
    email: str,
    *,
    count: int = 5,
    include_original: bool = False,
) -> list[str]:
    target_count = max(1, min(int(count or 1), 5))
    base_email = normalize_microsoft_alias_base_email(email)

    results: list[str] = []
    seen_emails: set[str] = set()

    if include_original:
        results.append(base_email)
        seen_emails.add(base_email)

    max_attempts = max(20, target_count * 20)
    attempts = 0
    while len(results) < target_count + (1 if include_original else 0) and attempts < max_attempts:
        candidate = generate_microsoft_alias_email(base_email)
        attempts += 1
        if candidate in seen_emails:
            continue
        seen_emails.add(candidate)
        results.append(candidate)

    if not results:
        results.append(base_email)
    return results
